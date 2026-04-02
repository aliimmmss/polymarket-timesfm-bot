"""
Validation utilities for Polymarket Trading Bot.

This module provides data validation and schema checking utilities.
"""

import re
import json
from typing import Dict, List, Optional, Any, Tuple, Union, Callable
from datetime import datetime
import numpy as np
import pandas as pd
from pydantic import BaseModel, ValidationError, validator, Field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ValidationErrorDetail(BaseModel):
    """Detailed validation error."""
    field: str
    value: Any
    error: str
    constraint: Optional[str] = None


class ValidationResult(BaseModel):
    """Result of validation operation."""
    is_valid: bool
    errors: List[ValidationErrorDetail] = []
    warnings: List[str] = []
    metadata: Dict[str, Any] = {}


class MarketStatus(Enum):
    """Market status enumeration."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    RESOLVED = "resolved"
    PAUSED = "paused"
    CLOSED = "closed"


class MarketDataSchema(BaseModel):
    """Schema for market data validation."""
    market_id: str
    question: str
    yes_price: float = Field(ge=0.0, le=1.0)
    no_price: float = Field(ge=0.0, le=1.0)
    liquidity_usd: float = Field(ge=0.0)
    daily_volume_usd: float = Field(ge=0.0)
    days_to_resolution: Optional[int] = Field(ge=0)
    status: MarketStatus
    created_at: datetime
    updated_at: datetime
    
    @validator('no_price')
    def validate_probabilities(cls, v, values):
        """Validate that yes_price + no_price ≈ 1.0."""
        if 'yes_price' in values:
            yes_price = values['yes_price']
            total = yes_price + v
            if abs(total - 1.0) > 0.01:  # Allow small rounding errors
                raise ValueError(f"Probability sum {total:.4f} deviates from 1.0")
        return v
    
    @validator('days_to_resolution')
    def validate_days_to_resolution(cls, v):
        """Validate days to resolution."""
        if v is not None and v > 365:
            raise ValueError(f"Days to resolution {v} exceeds 1 year")
        return v


class TradeSignalSchema(BaseModel):
    """Schema for trade signal validation."""
    market_id: str
    signal_type: str  # e.g., "BUY_YES", "SELL_NO"
    timestamp: datetime
    current_price: float = Field(ge=0.0, le=1.0)
    target_price: Optional[float] = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    position_size_pct: float = Field(ge=0.0, le=0.2)  # Max 20% position
    stop_loss: Optional[float] = Field(ge=0.0, le=1.0)
    take_profit: Optional[float] = Field(ge=0.0, le=1.0)
    rationale: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    
    @validator('signal_type')
    def validate_signal_type(cls, v):
        """Validate signal type."""
        valid_types = {"BUY_YES", "SELL_YES", "BUY_NO", "SELL_NO"}
        if v not in valid_types:
            raise ValueError(f"Invalid signal type: {v}")
        return v
    
    @validator('stop_loss', 'take_profit')
    def validate_price_relationships(cls, v, values, field):
        """Validate price relationships."""
        if v is None:
            return v
        
        signal_type = values.get('signal_type')
        current_price = values.get('current_price')
        
        if signal_type and current_price:
            if signal_type == "BUY_YES":
                # For BUY_YES: stop_loss < current_price < take_profit
                if field.name == 'stop_loss' and v >= current_price:
                    raise ValueError(f"Stop loss {v} must be less than current price {current_price}")
                if field.name == 'take_profit' and v <= current_price:
                    raise ValueError(f"Take profit {v} must be greater than current price {current_price}")
            elif signal_type == "SELL_YES":
                # For SELL_YES: take_profit < current_price < stop_loss
                if field.name == 'take_profit' and v >= current_price:
                    raise ValueError(f"Take profit {v} must be less than current price {current_price}")
                if field.name == 'stop_loss' and v <= current_price:
                    raise ValueError(f"Stop loss {v} must be greater than current price {current_price}")
        
        return v


class ValidationUtils:
    """Utility class for validation operations."""
    
    @staticmethod
    def validate_market_data(data: Dict[str, Any]) -> ValidationResult:
        """
        Validate market data.
        
        Args:
            data: Market data dictionary
            
        Returns:
            ValidationResult
        """
        errors = []
        warnings = []
        
        try:
            # Validate using schema
            market = MarketDataSchema(**data)
            
            # Additional business logic validation
            if market.yes_price + market.no_price < 0.99:
                warnings.append(f"Probability sum {market.yes_price + market.no_price:.4f} < 0.99")
            
            if market.liquidity_usd < 100:
                warnings.append(f"Low liquidity: ${market.liquidity_usd:.2f}")
            
            if market.daily_volume_usd < 10:
                warnings.append(f"Low daily volume: ${market.daily_volume_usd:.2f}")
            
            if market.days_to_resolution and market.days_to_resolution < 1:
                warnings.append(f"Market resolves in less than 1 day")
            
            return ValidationResult(
                is_valid=True,
                errors=errors,
                warnings=warnings,
                metadata={"validated_market": market.dict()}
            )
            
        except ValidationError as e:
            for error in e.errors():
                errors.append(ValidationErrorDetail(
                    field=".".join(str(loc) for loc in error["loc"]),
                    value=data.get(error["loc"][0]) if error["loc"] else None,
                    error=error["msg"],
                    constraint=error.get("type")
                ))
            
            return ValidationResult(
                is_valid=False,
                errors=errors,
                warnings=warnings,
                metadata={"validation_error": str(e)}
            )
    
    @staticmethod
    def validate_trade_signal(data: Dict[str, Any]) -> ValidationResult:
        """
        Validate trade signal.
        
        Args:
            data: Trade signal dictionary
            
        Returns:
            ValidationResult
        """
        errors = []
        warnings = []
        
        try:
            # Validate using schema
            signal = TradeSignalSchema(**data)
            
            # Additional business logic validation
            if signal.confidence < 0.5:
                warnings.append(f"Low confidence: {signal.confidence:.2f}")
            
            if signal.position_size_pct > 0.1:
                warnings.append(f"Large position size: {signal.position_size_pct:.1%}")
            
            if signal.stop_loss is not None and signal.take_profit is not None:
                # Check stop loss/take profit spread
                if signal.signal_type in ["BUY_YES", "BUY_NO"]:
                    spread = signal.take_profit - signal.stop_loss
                    if spread < 0.01:  # Less than 1% spread
                        warnings.append(f"Small risk/reward spread: {spread:.4f}")
            
            return ValidationResult(
                is_valid=True,
                errors=errors,
                warnings=warnings,
                metadata={"validated_signal": signal.dict()}
            )
            
        except ValidationError as e:
            for error in e.errors():
                errors.append(ValidationErrorDetail(
                    field=".".join(str(loc) for loc in error["loc"]),
                    value=data.get(error["loc"][0]) if error["loc"] else None,
                    error=error["msg"],
                    constraint=error.get("type")
                ))
            
            return ValidationResult(
                is_valid=False,
                errors=errors,
                warnings=warnings,
                metadata={"validation_error": str(e)}
            )
    
    @staticmethod
    def validate_price_history(
        prices: List[float],
        timestamps: Optional[List[datetime]] = None
    ) -> ValidationResult:
        """
        Validate price history data.
        
        Args:
            prices: List of prices
            timestamps: Optional list of timestamps
            
        Returns:
            ValidationResult
        """
        errors = []
        warnings = []
        
        # Convert to numpy array for analysis
        price_array = np.array(prices)
        
        # Check basic validity
        if len(price_array) == 0:
            errors.append(ValidationErrorDetail(
                field="prices",
                value=prices,
                error="Price history is empty",
                constraint="non_empty"
            ))
        
        if np.any(np.isnan(price_array)):
            nan_count = np.sum(np.isnan(price_array))
            errors.append(ValidationErrorDetail(
                field="prices",
                value=f"Array with {nan_count} NaN values",
                error=f"Price history contains {nan_count} NaN values",
                constraint="no_nan"
            ))
        
        if np.any(price_array < 0):
            negative_count = np.sum(price_array < 0)
            errors.append(ValidationErrorDetail(
                field="prices",
                value=f"Array with {negative_count} negative values",
                error=f"Price history contains {negative_count} negative values",
                constraint="non_negative"
            ))
        
        if np.any(price_array > 1):
            above_one_count = np.sum(price_array > 1)
            warnings.append(f"Price history contains {above_one_count} values > 1.0")
        
        # Check for extreme outliers
        if len(price_array) >= 10:
            q1 = np.percentile(price_array, 25)
            q3 = np.percentile(price_array, 75)
            iqr = q3 - q1
            
            if iqr > 0:
                lower_bound = q1 - 3 * iqr
                upper_bound = q3 + 3 * iqr
                
                outliers = price_array[(price_array < lower_bound) | (price_array > upper_bound)]
                if len(outliers) > 0:
                    warnings.append(f"Found {len(outliers)} potential outliers in price history")
        
        # Check timestamp consistency if provided
        if timestamps:
            if len(timestamps) != len(prices):
                errors.append(ValidationErrorDetail(
                    field="timestamps",
                    value=f"Length {len(timestamps)}",
                    error=f"Timestamp length {len(timestamps)} doesn't match price length {len(prices)}",
                    constraint="same_length"
                ))
            else:
                # Check for chronological order
                for i in range(1, len(timestamps)):
                    if timestamps[i] <= timestamps[i-1]:
                        warnings.append(f"Timestamps not strictly increasing at index {i}")
                        break
        
        is_valid = len(errors) == 0
        
        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            metadata={
                "price_stats": {
                    "count": len(price_array),
                    "mean": float(np.mean(price_array)) if len(price_array) > 0 else None,
                    "std": float(np.std(price_array)) if len(price_array) > 0 else None,
                    "min": float(np.min(price_array)) if len(price_array) > 0 else None,
                    "max": float(np.max(price_array)) if len(price_array) > 0 else None,
                }
            }
        )
    
    @staticmethod
    def validate_portfolio_state(data: Dict[str, Any]) -> ValidationResult:
        """
        Validate portfolio state data.
        
        Args:
            data: Portfolio state dictionary
            
        Returns:
            ValidationResult
        """
        errors = []
        warnings = []
        
        # Check required fields
        required_fields = ["cash_balance", "portfolio_value", "positions"]
        for field in required_fields:
            if field not in data:
                errors.append(ValidationErrorDetail(
                    field=field,
                    value=None,
                    error=f"Missing required field: {field}",
                    constraint="required"
                ))
        
        if errors:
            return ValidationResult(
                is_valid=False,
                errors=errors,
                warnings=warnings
            )
        
        # Validate cash balance
        cash_balance = data["cash_balance"]
        if not isinstance(cash_balance, (int, float)):
            errors.append(ValidationErrorDetail(
                field="cash_balance",
                value=cash_balance,
                error="Cash balance must be numeric",
                constraint="numeric"
            ))
        elif cash_balance < 0:
            warnings.append(f"Negative cash balance: ${cash_balance:.2f}")
        
        # Validate portfolio value
        portfolio_value = data["portfolio_value"]
        if not isinstance(portfolio_value, (int, float)):
            errors.append(ValidationErrorDetail(
                field="portfolio_value",
                value=portfolio_value,
                error="Portfolio value must be numeric",
                constraint="numeric"
            ))
        elif portfolio_value < 0:
            warnings.append(f"Negative portfolio value: ${portfolio_value:.2f}")
        
        # Validate positions
        positions = data.get("positions", [])
        if not isinstance(positions, list):
            errors.append(ValidationErrorDetail(
                field="positions",
                value=positions,
                error="Positions must be a list",
                constraint="list"
            ))
        else:
            for i, position in enumerate(positions):
                if not isinstance(position, dict):
                    errors.append(ValidationErrorDetail(
                        field=f"positions[{i}]",
                        value=position,
                        error="Position must be a dictionary",
                        constraint="dict"
                    ))
                    continue
                
                # Check position fields
                pos_fields = ["market_id", "position_type", "quantity", "current_price"]
                for field in pos_fields:
                    if field not in position:
                        warnings.append(f"Position {i} missing field: {field}")
        
        # Check consistency
        if ("cash_balance" in data and "portfolio_value" in data and 
            isinstance(data["cash_balance"], (int, float)) and 
            isinstance(data["portfolio_value"], (int, float))):
            
            # Calculate position value from positions if available
            if isinstance(positions, list):
                calculated_position_value = 0.0
                for position in positions:
                    if isinstance(position, dict):
                        quantity = position.get("quantity", 0)
                        price = position.get("current_price", 0)
                        if isinstance(quantity, (int, float)) and isinstance(price, (int, float)):
                            calculated_position_value += quantity * price
                
                calculated_total = data["cash_balance"] + calculated_position_value
                
                # Allow small discrepancies due to rounding
                discrepancy = abs(calculated_total - data["portfolio_value"])
                if discrepancy > 1.0:  # More than $1 discrepancy
                    warnings.append(f"Portfolio value discrepancy: ${discrepancy:.2f}")
        
        is_valid = len(errors) == 0
        
        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            metadata={
                "portfolio_stats": {
                    "cash_balance": cash_balance if isinstance(cash_balance, (int, float)) else None,
                    "portfolio_value": portfolio_value if isinstance(portfolio_value, (int, float)) else None,
                    "position_count": len(positions) if isinstance(positions, list) else 0,
                }
            }
        )
    
    @staticmethod
    def validate_configuration(config: Dict[str, Any]) -> ValidationResult:
        """
        Validate bot configuration.
        
        Args:
            config: Configuration dictionary
            
        Returns:
            ValidationResult
        """
        errors = []
        warnings = []
        
        # Check required top-level fields
        required_fields = ["bot", "data_collection", "trade_execution", "portfolio_management"]
        for field in required_fields:
            if field not in config:
                errors.append(ValidationErrorDetail(
                    field=field,
                    value=None,
                    error=f"Missing required configuration section: {field}",
                    constraint="required"
                ))
        
        if errors:
            return ValidationResult(
                is_valid=False,
                errors=errors,
                warnings=warnings
            )
        
        # Validate bot configuration
        bot_config = config.get("bot", {})
        if "cycle_interval_minutes" not in bot_config:
            errors.append(ValidationErrorDetail(
                field="bot.cycle_interval_minutes",
                value=None,
                error="Missing cycle interval",
                constraint="required"
            ))
        else:
            interval = bot_config["cycle_interval_minutes"]
            if not isinstance(interval, (int, float)):
                errors.append(ValidationErrorDetail(
                    field="bot.cycle_interval_minutes",
                    value=interval,
                    error="Cycle interval must be numeric",
                    constraint="numeric"
                ))
            elif interval < 1:
                errors.append(ValidationErrorDetail(
                    field="bot.cycle_interval_minutes",
                    value=interval,
                    error="Cycle interval must be at least 1 minute",
                    constraint="min_1"
                ))
            elif interval > 1440:
                warnings.append(f"Long cycle interval: {interval} minutes")
        
        # Validate trade execution
        trade_config = config.get("trade_execution", {})
        if "paper_trading" not in trade_config:
            warnings.append("paper_trading not specified, defaulting to True")
        
        if "max_position_size_usd" not in trade_config:
            errors.append(ValidationErrorDetail(
                field="trade_execution.max_position_size_usd",
                value=None,
                error="Missing maximum position size",
                constraint="required"
            ))
        else:
            max_size = trade_config["max_position_size_usd"]
            if not isinstance(max_size, (int, float)):
                errors.append(ValidationErrorDetail(
                    field="trade_execution.max_position_size_usd",
                    value=max_size,
                    error="Maximum position size must be numeric",
                    constraint="numeric"
                ))
            elif max_size <= 0:
                errors.append(ValidationErrorDetail(
                    field="trade_execution.max_position_size_usd",
                    value=max_size,
                    error="Maximum position size must be positive",
                    constraint="positive"
                ))
        
        # Validate portfolio management
        portfolio_config = config.get("portfolio_management", {})
        if "initial_capital" not in portfolio_config:
            errors.append(ValidationErrorDetail(
                field="portfolio_management.initial_capital",
                value=None,
                error="Missing initial capital",
                constraint="required"
            ))
        else:
            capital = portfolio_config["initial_capital"]
            if not isinstance(capital, (int, float)):
                errors.append(ValidationErrorDetail(
                    field="portfolio_management.initial_capital",
                    value=capital,
                    error="Initial capital must be numeric",
                    constraint="numeric"
                ))
            elif capital <= 0:
                errors.append(ValidationErrorDetail(
                    field="portfolio_management.initial_capital",
                    value=capital,
                    error="Initial capital must be positive",
                    constraint="positive"
                ))
        
        # Check for deprecated or unknown fields
        known_sections = [
            "bot", "data_collection", "feature_engineering", "forecasting",
            "signal_generation", "trade_execution", "portfolio_management",
            "risk_management", "performance_tracking", "logging", "scheduler"
        ]
        
        for section in config.keys():
            if section not in known_sections:
                warnings.append(f"Unknown configuration section: {section}")
        
        is_valid = len(errors) == 0
        
        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            metadata={
                "config_summary": {
                    "sections": list(config.keys()),
                    "bot_interval": bot_config.get("cycle_interval_minutes"),
                    "paper_trading": trade_config.get("paper_trading", True),
                    "initial_capital": portfolio_config.get("initial_capital"),
                }
            }
        )
    
    @staticmethod
    def validate_email(email: str) -> bool:
        """Validate email address format."""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None
    
    @staticmethod
    def validate_url(url: str) -> bool:
        """Validate URL format."""
        pattern = r'^https?://[^\s/$.?#].[^\s]*$'
        return re.match(pattern, url) is not None
    
    @staticmethod
    def validate_numeric_range(
        value: Any,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
        allow_none: bool = False
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate numeric value is within range.
        
        Args:
            value: Value to validate
            min_value: Minimum allowed value
            max_value: Maximum allowed value
            allow_none: Whether None is allowed
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if value is None:
            if allow_none:
                return True, None
            else:
                return False, "Value cannot be None"
        
        try:
            num_value = float(value)
        except (ValueError, TypeError):
            return False, f"Value '{value}' is not numeric"
        
        if min_value is not None and num_value < min_value:
            return False, f"Value {num_value} is less than minimum {min_value}"
        
        if max_value is not None and num_value > max_value:
            return False, f"Value {num_value} is greater than maximum {max_value}"
        
        return True, None
    
    @staticmethod
    def validate_list_length(
        items: List[Any],
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        exact_length: Optional[int] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate list length constraints.
        
        Args:
            items: List to validate
            min_length: Minimum allowed length
            max_length: Maximum allowed length
            exact_length: Exact required length
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not isinstance(items, list):
            return False, f"Expected list, got {type(items)}"
        
        length = len(items)
        
        if exact_length is not None and length != exact_length:
            return False, f"List length {length} != required length {exact_length}"
        
        if min_length is not None and length < min_length:
            return False, f"List length {length} < minimum {min_length}"
        
        if max_length is not None and length > max_length:
            return False, f"List length {length} > maximum {max_length}"
        
        return True, None
    
    @staticmethod
    def create_validator(
        validation_func: Callable,
        error_message: str
    ) -> Callable[[Any], Tuple[bool, Optional[str]]]:
        """
        Create a reusable validator function.
        
        Args:
            validation_func: Function that returns bool
            error_message: Error message if validation fails
            
        Returns:
            Validator function
        """
        def validator(value: Any) -> Tuple[bool, Optional[str]]:
            try:
                if validation_func(value):
                    return True, None
                else:
                    return False, error_message
            except Exception as e:
                return False, f"Validation error: {str(e)}"
        
        return validator


if __name__ == "__main__":
    # Test ValidationUtils
    print("Testing ValidationUtils...")
    
    # Test market data validation
    market_data = {
        "market_id": "market_001",
        "question": "Will BTC exceed $100K by 2025?",
        "yes_price": 0.65,
        "no_price": 0.35,
        "liquidity_usd": 5000.0,
        "daily_volume_usd": 1000.0,
        "days_to_resolution": 180,
        "status": "active",
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
    
    market_result = ValidationUtils.validate_market_data(market_data)
    print(f"Market validation: {'VALID' if market_result.is_valid else 'INVALID'}")
    if market_result.errors:
        for error in market_result.errors:
            print(f"  Error: {error.field}: {error.error}")
    if market_result.warnings:
        for warning in market_result.warnings:
            print(f"  Warning: {warning}")
    
    # Test trade signal validation
    trade_signal = {
        "market_id": "market_001",
        "signal_type": "BUY_YES",
        "timestamp": datetime.now(),
        "current_price": 0.65,
        "target_price": 0.75,
        "confidence": 0.8,
        "position_size_pct": 0.05,
        "stop_loss": 0.60,
        "take_profit": 0.80,
        "rationale": "Probability mispricing detected",
    }
    
    signal_result = ValidationUtils.validate_trade_signal(trade_signal)
    print(f"\nSignal validation: {'VALID' if signal_result.is_valid else 'INVALID'}")
    if signal_result.errors:
        for error in signal_result.errors:
            print(f"  Error: {error.field}: {error.error}")
    
    # Test price history validation
    prices = [0.65, 0.66, 0.64, 0.67, 0.63, 0.68, 0.62]
    price_result = ValidationUtils.validate_price_history(prices)
    print(f"\nPrice history validation: {'VALID' if price_result.is_valid else 'INVALID'}")
    
    # Test portfolio validation
    portfolio_state = {
        "cash_balance": 8000.0,
        "portfolio_value": 10500.0,
        "positions": [
            {
                "market_id": "market_001",
                "position_type": "YES",
                "quantity": 100.0,
                "current_price": 0.65,
                "average_price": 0.60,
            }
        ]
    }
    
    portfolio_result = ValidationUtils.validate_portfolio_state(portfolio_state)
    print(f"\nPortfolio validation: {'VALID' if portfolio_result.is_valid else 'INVALID'}")
    
    # Test configuration validation
    sample_config = {
        "bot": {
            "cycle_interval_minutes": 60,
        },
        "trade_execution": {
            "paper_trading": True,
            "max_position_size_usd": 1000.0,
        },
        "portfolio_management": {
            "initial_capital": 10000.0,
        },
        "data_collection": {},
    }
    
    config_result = ValidationUtils.validate_configuration(sample_config)
    print(f"\nConfig validation: {'VALID' if config_result.is_valid else 'INVALID'}")
    
    # Test utility validators
    print(f"\nEmail validation:")
    print(f"  'test@example.com': {ValidationUtils.validate_email('test@example.com')}")
    print(f"  'invalid-email': {ValidationUtils.validate_email('invalid-email')}")
    
    print(f"\nNumeric range validation:")
    is_valid, error = ValidationUtils.validate_numeric_range(5, min_value=0, max_value=10)
    print(f"  5 in [0, 10]: {is_valid} (error: {error})")
    
    print(f"\nList length validation:")
    is_valid, error = ValidationUtils.validate_list_length([1, 2, 3], min_length=2, max_length=5)
    print(f"  [1,2,3] length in [2,5]: {is_valid} (error: {error})")
    
    print("\nValidationUtils test completed")