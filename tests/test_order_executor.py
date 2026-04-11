"""Tests for the order executor."""

import pytest
from unittest.mock import patch, MagicMock
from src.trading.order_executor import OrderExecutor, Order


class TestOrderExecutor:
    """Test cases for order execution."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.executor = OrderExecutor(dry_run=True)
        
    def test_initialization_dry_run(self):
        """Test executor initializes in dry run mode."""
        executor = OrderExecutor(dry_run=True)
        assert executor.dry_run is True
        assert executor.max_order_size == 10.0
        assert executor.daily_loss_limit == 20.0
        
    def test_initialization_live_mode_no_key(self):
        """Test that live mode requires private key."""
        with pytest.raises(ValueError) as exc_info:
            OrderExecutor(dry_run=False)
        assert "PRIVATE_KEY required" in str(exc_info.value)
        
    @patch.dict('os.environ', {'PRIVATE_KEY': 'test_key', 'FUNDER_ADDRESS': 'test_addr'})
    def test_initialization_live_mode_with_key(self):
        """Test that live mode works with private key."""
        with patch('src.trading.order_executor.ClobClient'):
            executor = OrderExecutor(dry_run=False)
            assert executor.dry_run is False
            
    def test_buy_token_dry_run(self):
        """Test buy token in dry run mode."""
        result = self.executor.buy_token('test_token', price=0.55, size_usdc=5.0)
        
        assert result['success'] is True
        assert result['side'] == 'BUY'
        assert result['dry_run'] is True
        assert 'order_id' in result
        assert result['price'] == 0.55
        assert result['size'] == 5.0
        
    def test_buy_token_exceeds_max_size(self):
        """Test that max order size is enforced."""
        result = self.executor.buy_token('test_token', price=0.55, size_usdc=50.0)  # > 10
        
        # Should be capped at max
        assert result['size'] <= self.executor.max_order_size
        
    def test_buy_token_daily_loss_limit_reached(self):
        """Test that trading stops when daily loss limit reached."""
        # Manually set daily P&L
        self.executor._daily_pnl = -25.0  # Below -20 limit
        
        result = self.executor.buy_token('test_token', price=0.55, size_usdc=5.0)
        
        assert result['success'] is False
        assert 'Daily loss limit reached' in result['error']
        
    def test_buy_token_invalid_price(self):
        """Test price validation."""
        # Price should be clipped to 0.01-0.99 range
        result = self.executor.buy_token('test_token', price=1.05, size_usdc=5.0)
        assert result['price'] <= 0.99
        
        result = self.executor.buy_token('test_token', price=-0.05, size_usdc=5.0)
        assert result['price'] >= 0.01
        
    def test_sell_token_dry_run(self):
        """Test sell token in dry run mode."""
        result = self.executor.sell_token('test_token', price=0.95, size_tokens=5.0)
        
        assert result['success'] is True
        assert result['side'] == 'SELL'
        assert result['dry_run'] is True
        assert result['price'] == 0.95
        
    def test_order_tracking(self):
        """Test that orders are tracked."""
        initial_count = len(self.executor._orders)
        
        self.executor.buy_token('test_token', price=0.55, size_usdc=5.0)
        
        assert len(self.executor._orders) == initial_count + 1
        order = self.executor._orders[-1]
        assert order.side == 'BUY'
        assert order.status == 'DRY_RUN'
        
    def test_cancel_order_dry_run(self):
        """Test cancel in dry run mode."""
        result = self.executor.cancel_order('test_order_123')
        assert result is True
        
    def test_get_order_status_dry_run(self):
        """Test status check in dry run mode."""
        result = self.executor.get_order_status('DRY_RUN_123')
        assert result['status'] == 'DRY_RUN'
        assert result['filled'] is False
        
    def test_update_pnl(self):
        """Test P&L tracking."""
        self.executor.update_pnl(10.0)
        assert self.executor._daily_pnl == 10.0
        
        self.executor.update_pnl(-5.0)
        assert self.executor._daily_pnl == 5.0
        
    def test_reset_daily_limits(self):
        """Test daily limit reset."""
        self.executor._daily_pnl = -50.0
        self.executor.reset_daily_limits()
        assert self.executor._daily_pnl == 0.0
