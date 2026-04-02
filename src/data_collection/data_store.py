"""
Database storage module for Polymarket Trading Bot.

This module handles:
- PostgreSQL database schema and connections
- Storing market data and prices
- Querying historical data for forecasting
- Managing feature storage
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import logging
from dataclasses import dataclass
import json

from sqlalchemy import (
    create_engine, Column, String, Float, DateTime, 
    Boolean, Integer, JSON, Text, ForeignKey, UniqueConstraint,
    BigInteger, func
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import QueuePool

logger = logging.getLogger(__name__)

Base = declarative_base()


class Market(Base):
    """Database model for Polymarket markets."""
    __tablename__ = "markets"
    
    id = Column(String, primary_key=True)  # Polymarket market ID
    slug = Column(String, nullable=False, index=True)
    question = Column(Text, nullable=False)
    description = Column(Text)
    category = Column(String, nullable=False, index=True)
    subcategory = Column(String)
    resolution_source = Column(String, nullable=False)
    resolution_date = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False)
    liquidity_usd = Column(Float, default=0.0)
    volume_24h_usd = Column(Float, default=0.0)
    active = Column(Boolean, default=True, index=True)
    last_updated = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relationships
    prices = relationship("MarketPrice", back_populates="market", cascade="all, delete-orphan")
    features = relationship("MarketFeature", back_populates="market", cascade="all, delete-orphan")


class MarketPrice(Base):
    """Database model for market price snapshots."""
    __tablename__ = "market_prices"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    market_id = Column(String, ForeignKey("markets.id"), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    yes_price = Column(Float, nullable=False)
    no_price = Column(Float, nullable=False)
    yes_volume = Column(Float, default=0.0)
    no_volume = Column(Float, default=0.0)
    total_volume = Column(Float, default=0.0)
    liquidity_usd = Column(Float, default=0.0)
    
    # Unique constraint on market_id and timestamp
    __table_args__ = (UniqueConstraint("market_id", "timestamp", name="uix_market_timestamp"),)
    
    # Relationships
    market = relationship("Market", back_populates="prices")


class MarketFeature(Base):
    """Database model for engineered features."""
    __tablename__ = "market_features"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    market_id = Column(String, ForeignKey("markets.id"), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    feature_type = Column(String, nullable=False, index=True)  # e.g., "technical", "volume", "sentiment"
    feature_name = Column(String, nullable=False)  # e.g., "sma_24", "rsi_14"
    feature_value = Column(Float, nullable=False)
    metadata = Column(JSON)  # Additional context about the feature
    
    # Relationships
    market = relationship("Market", back_populates="features")
    
    # Unique constraint
    __table_args__ = (
        UniqueConstraint("market_id", "timestamp", "feature_type", "feature_name", 
                        name="uix_market_feature"),
    )


class Forecast(Base):
    """Database model for TimesFM forecasts."""
    __tablename__ = "forecasts"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    market_id = Column(String, ForeignKey("markets.id"), nullable=False, index=True)
    forecast_timestamp = Column(DateTime, nullable=False, index=True)  # When forecast was made
    forecast_horizon = Column(Integer, nullable=False)  # Hours ahead
    point_forecast = Column(Float, nullable=False)  # Median forecast
    quantile_10 = Column(Float)  # 10th percentile
    quantile_30 = Column(Float)  # 30th percentile
    quantile_50 = Column(Float)  # 50th percentile (same as point_forecast)
    quantile_70 = Column(Float)  # 70th percentile
    quantile_90 = Column(Float)  # 90th percentile
    confidence_width = Column(Float)  # quantile_90 - quantile_10
    inputs_used = Column(JSON)  # Input features used for forecasting
    model_version = Column(String)  # TimesFM model version
    
    # Relationships
    market = relationship("Market")


class Trade(Base):
    """Database model for executed trades."""
    __tablename__ = "trades"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    market_id = Column(String, ForeignKey("markets.id"), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    trade_type = Column(String, nullable=False)  # "BUY_YES", "SELL_YES", "BUY_NO", "SELL_NO"
    quantity = Column(Float, nullable=False)  # Number of shares
    price = Column(Float, nullable=False)  # Price per share
    total_usd = Column(Float, nullable=False)  # quantity * price
    fee_usd = Column(Float, default=0.0)
    slippage = Column(Float, default=0.0)  # Percentage slippage
    strategy = Column(String)  # Which strategy triggered this trade
    forecast_id = Column(BigInteger, ForeignKey("forecasts.id"))  # Associated forecast
    paper_trade = Column(Boolean, default=True, index=True)  # Paper vs live trade
    
    # Relationships
    market = relationship("Market")
    forecast = relationship("Forecast")


class Portfolio(Base):
    """Database model for portfolio snapshots."""
    __tablename__ = "portfolio_snapshots"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    total_value = Column(Float, nullable=False)
    cash_balance = Column(Float, nullable=False)
    invested_amount = Column(Float, nullable=False)
    daily_pnl = Column(Float)
    daily_return = Column(Float)
    drawdown = Column(Float)
    sharpe_ratio_30d = Column(Float)
    max_position_size = Column(Float)
    active_positions = Column(Integer)
    risk_score = Column(Float)  # 0-1 risk score
    metadata = Column(JSON)  # Additional portfolio metrics


class DataStore:
    """Database store for Polymarket data."""
    
    def __init__(self, database_url: str, echo: bool = False):
        """
        Initialize data store.
        
        Args:
            database_url: PostgreSQL connection URL
            echo: Whether to log SQL queries
        """
        self.database_url = database_url
        self.async_engine = create_async_engine(
            database_url,
            echo=echo,
            poolclass=QueuePool,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True
        )
        self.async_session_factory = async_sessionmaker(
            self.async_engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        # Synchronous engine for migrations and simple queries
        sync_url = database_url.replace("postgresql+asyncpg", "postgresql")
        self.sync_engine = create_engine(
            sync_url,
            echo=echo,
            poolclass=QueuePool,
            pool_size=10,
            max_overflow=20
        )
        self.SyncSession = sessionmaker(bind=self.sync_engine)
        
        logger.info(f"Initialized DataStore with URL: {database_url}")
    
    async def init_db(self):
        """Initialize database tables."""
        async with self.async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created")
    
    def sync_init_db(self):
        """Synchronous version of init_db."""
        Base.metadata.create_all(self.sync_engine)
        logger.info("Database tables created (sync)")
    
    async def store_market(self, market_data: Dict[str, Any]) -> Optional[Market]:
        """
        Store or update a market in the database.
        
        Args:
            market_data: Dictionary with market data
            
        Returns:
            Market object if successful, None otherwise
        """
        async with self.async_session_factory() as session:
            try:
                # Check if market exists
                market = await session.get(Market, market_data["id"])
                
                if market:
                    # Update existing market
                    for key, value in market_data.items():
                        if hasattr(market, key):
                            setattr(market, key, value)
                else:
                    # Create new market
                    market = Market(**market_data)
                    session.add(market)
                
                await session.commit()
                logger.debug(f"Stored market: {market_data['id']}")
                return market
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Error storing market {market_data.get('id')}: {e}")
                return None
    
    async def store_price(self, price_data: Dict[str, Any]) -> bool:
        """
        Store a price snapshot for a market.
        
        Args:
            price_data: Dictionary with price data
            
        Returns:
            True if successful, False otherwise
        """
        async with self.async_session_factory() as session:
            try:
                # Check if price already exists for this timestamp
                existing = await session.execute(
                    session.query(MarketPrice)
                    .filter(
                        MarketPrice.market_id == price_data["market_id"],
                        MarketPrice.timestamp == price_data["timestamp"]
                    )
                )
                
                if existing.scalar_one_or_none():
                    logger.debug(f"Price already exists for {price_data['market_id']} at {price_data['timestamp']}")
                    return True
                
                price = MarketPrice(**price_data)
                session.add(price)
                await session.commit()
                
                logger.debug(f"Stored price for market {price_data['market_id']}")
                return True
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Error storing price: {e}")
                return False
    
    async def get_market_prices(
        self, 
        market_id: str, 
        start_time: datetime, 
        end_time: datetime,
        limit: int = 1000
    ) -> List[MarketPrice]:
        """
        Get price history for a market.
        
        Args:
            market_id: Market ID
            start_time: Start time
            end_time: End time
            limit: Maximum number of prices to return
            
        Returns:
            List of MarketPrice objects
        """
        async with self.async_session_factory() as session:
            try:
                result = await session.execute(
                    session.query(MarketPrice)
                    .filter(
                        MarketPrice.market_id == market_id,
                        MarketPrice.timestamp >= start_time,
                        MarketPrice.timestamp <= end_time
                    )
                    .order_by(MarketPrice.timestamp.asc())
                    .limit(limit)
                )
                
                prices = result.scalars().all()
                logger.debug(f"Retrieved {len(prices)} prices for market {market_id}")
                return prices
                
            except Exception as e:
                logger.error(f"Error getting prices for market {market_id}: {e}")
                return []
    
    async def get_latest_price(self, market_id: str) -> Optional[MarketPrice]:
        """
        Get the latest price for a market.
        
        Args:
            market_id: Market ID
            
        Returns:
            Latest MarketPrice or None if not found
        """
        async with self.async_session_factory() as session:
            try:
                result = await session.execute(
                    session.query(MarketPrice)
                    .filter(MarketPrice.market_id == market_id)
                    .order_by(MarketPrice.timestamp.desc())
                    .limit(1)
                )
                
                price = result.scalar_one_or_none()
                return price
                
            except Exception as e:
                logger.error(f"Error getting latest price for market {market_id}: {e}")
                return None
    
    async def store_forecast(self, forecast_data: Dict[str, Any]) -> Optional[Forecast]:
        """
        Store a TimesFM forecast.
        
        Args:
            forecast_data: Dictionary with forecast data
            
        Returns:
            Forecast object if successful, None otherwise
        """
        async with self.async_session_factory() as session:
            try:
                forecast = Forecast(**forecast_data)
                session.add(forecast)
                await session.commit()
                
                logger.debug(f"Stored forecast for market {forecast_data.get('market_id')}")
                return forecast
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Error storing forecast: {e}")
                return None
    
    async def get_recent_forecasts(
        self, 
        market_id: str, 
        hours: int = 24
    ) -> List[Forecast]:
        """
        Get recent forecasts for a market.
        
        Args:
            market_id: Market ID
            hours: Number of hours to look back
            
        Returns:
            List of Forecast objects
        """
        async with self.async_session_factory() as session:
            try:
                cutoff = datetime.utcnow() - timedelta(hours=hours)
                
                result = await session.execute(
                    session.query(Forecast)
                    .filter(
                        Forecast.market_id == market_id,
                        Forecast.forecast_timestamp >= cutoff
                    )
                    .order_by(Forecast.forecast_timestamp.desc())
                )
                
                forecasts = result.scalars().all()
                logger.debug(f"Retrieved {len(forecasts)} recent forecasts for market {market_id}")
                return forecasts
                
            except Exception as e:
                logger.error(f"Error getting recent forecasts for market {market_id}: {e}")
                return []
    
    async def store_trade(self, trade_data: Dict[str, Any]) -> Optional[Trade]:
        """
        Store an executed trade.
        
        Args:
            trade_data: Dictionary with trade data
            
        Returns:
            Trade object if successful, None otherwise
        """
        async with self.async_session_factory() as session:
            try:
                trade = Trade(**trade_data)
                session.add(trade)
                await session.commit()
                
                logger.info(f"Stored trade: {trade_data.get('trade_type')} for market {trade_data.get('market_id')}")
                return trade
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Error storing trade: {e}")
                return None
    
    async def get_portfolio_value(self) -> float:
        """
        Get the latest portfolio value.
        
        Returns:
            Latest portfolio total value
        """
        async with self.async_session_factory() as session:
            try:
                result = await session.execute(
                    session.query(Portfolio.total_value)
                    .order_by(Portfolio.timestamp.desc())
                    .limit(1)
                )
                
                value = result.scalar_one_or_none()
                return value or 0.0
                
            except Exception as e:
                logger.error(f"Error getting portfolio value: {e}")
                return 0.0
    
    async def close(self):
        """Close database connections."""
        await self.async_engine.dispose()
        self.sync_engine.dispose()
        logger.info("Database connections closed")
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# Helper function to create database URL from environment variables
def create_database_url(
    host: str = "localhost",
    port: int = 5432,
    database: str = "polymarket_bot",
    user: str = "bot_user",
    password: str = "",
    asyncpg: bool = True
) -> str:
    """
    Create a database URL from components.
    
    Args:
        host: Database host
        port: Database port
        database: Database name
        user: Database user
        password: Database password
        asyncpg: Whether to use asyncpg driver
        
    Returns:
        Database URL string
    """
    driver = "asyncpg" if asyncpg else "psycopg2"
    return f"postgresql+{driver}://{user}:{password}@{host}:{port}/{database}"


if __name__ == "__main__":
    # Test the data store
    import asyncio
    from datetime import datetime
    
    async def test():
        # Create in-memory SQLite database for testing
        db_url = "sqlite+aiosqlite:///test.db"
        store = DataStore(db_url, echo=True)
        
        await store.init_db()
        
        # Test market storage
        market_data = {
            "id": "test_market_001",
            "slug": "test-will-event-happen",
            "question": "Will this test event happen?",
            "description": "A test market for development",
            "category": "testing",
            "subcategory": "unit_tests",
            "resolution_source": "api",
            "resolution_date": datetime(2024, 12, 31),
            "created_at": datetime.utcnow(),
            "liquidity_usd": 10000.0,
            "volume_24h_usd": 5000.0,
            "active": True
        }
        
        market = await store.store_market(market_data)
        print(f"Stored market: {market.id if market else 'Failed'}")
        
        # Test price storage
        price_data = {
            "market_id": "test_market_001",
            "timestamp": datetime.utcnow(),
            "yes_price": 0.65,
            "no_price": 0.35,
            "yes_volume": 100.0,
            "no_volume": 50.0,
            "total_volume": 150.0,
            "liquidity_usd": 10000.0
        }
        
        success = await store.store_price(price_data)
        print(f"Stored price: {'Success' if success else 'Failed'}")
        
        # Test retrieving prices
        prices = await store.get_market_prices(
            "test_market_001",
            datetime.utcnow() - timedelta(hours=1),
            datetime.utcnow()
        )
        print(f"Retrieved {len(prices)} prices")
        
        await store.close()
    
    asyncio.run(test())