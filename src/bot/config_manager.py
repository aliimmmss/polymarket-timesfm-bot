"""
Configuration manager for Polymarket Trading Bot.

This module handles:
- Configuration loading and validation
- Environment variable management
- Secure credential handling
- Configuration versioning and migration
"""

import os
import json
import yaml
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
import logging
from dataclasses import dataclass, asdict
import hashlib
from datetime import datetime
import copy

logger = logging.getLogger(__name__)


@dataclass
class BotConfig:
    """Container for bot configuration."""
    # Bot settings
    bot_name: str = "Polymarket Trading Bot"
    version: str = "1.0.0"
    environment: str = "development"  # development, staging, production
    
    # Execution settings
    paper_trading: bool = True
    cycle_interval_minutes: int = 60
    enable_scheduler: bool = True
    
    # Market filters
    market_filters: Dict[str, Any] = None
    
    # Component configurations
    data_collection: Dict[str, Any] = None
    feature_engineering: Dict[str, Any] = None
    forecasting: Dict[str, Any] = None
    signal_generation: Dict[str, Any] = None
    trade_execution: Dict[str, Any] = None
    portfolio_management: Dict[str, Any] = None
    risk_management: Dict[str, Any] = None
    performance_tracking: Dict[str, Any] = None
    
    # API credentials (encrypted)
    api_credentials: Dict[str, Any] = None
    
    # Logging
    logging_config: Dict[str, Any] = None
    
    def __post_init__(self):
        """Initialize nested dictionaries."""
        if self.market_filters is None:
            self.market_filters = {}
        
        if self.data_collection is None:
            self.data_collection = {}
        
        if self.feature_engineering is None:
            self.feature_engineering = {}
        
        if self.forecasting is None:
            self.forecasting = {}
        
        if self.signal_generation is None:
            self.signal_generation = {}
        
        if self.trade_execution is None:
            self.trade_execution = {}
        
        if self.portfolio_management is None:
            self.portfolio_management = {}
        
        if self.risk_management is None:
            self.risk_management = {}
        
        if self.performance_tracking is None:
            self.performance_tracking = {}
        
        if self.api_credentials is None:
            self.api_credentials = {}
        
        if self.logging_config is None:
            self.logging_config = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    def validate(self) -> Tuple[bool, List[str]]:
        """
        Validate configuration.
        
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        
        # Basic validation
        if not self.bot_name:
            errors.append("Bot name is required")
        
        if self.cycle_interval_minutes < 1:
            errors.append("Cycle interval must be at least 1 minute")
        
        if self.cycle_interval_minutes > 1440:
            errors.append("Cycle interval cannot exceed 24 hours")
        
        # Environment validation
        if self.environment not in ["development", "staging", "production"]:
            errors.append(f"Invalid environment: {self.environment}")
        
        # API validation for production
        if self.environment == "production" and self.paper_trading:
            errors.append("Paper trading cannot be enabled in production environment")
        
        # Forecasting validation
        if "model_version" not in self.forecasting:
            errors.append("Forecasting model_version is required")
        
        # Trade execution validation
        if "max_position_size_usd" not in self.trade_execution:
            errors.append("Trade execution max_position_size_usd is required")
        
        # Portfolio validation
        if "initial_capital" not in self.portfolio_management:
            errors.append("Portfolio management initial_capital is required")
        
        is_valid = len(errors) == 0
        return is_valid, errors
    
    def get_config_hash(self) -> str:
        """Get hash of configuration for change detection."""
        config_str = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(config_str.encode()).hexdigest()[:16]


class ConfigManager:
    """Manage bot configuration."""
    
    def __init__(self, config_dir: Optional[str] = None):
        """
        Initialize configuration manager.
        
        Args:
            config_dir: Directory for configuration files
        """
        # Determine config directory
        if config_dir:
            self.config_dir = Path(config_dir)
        else:
            # Default to ~/.polymarket-bot/config
            self.config_dir = Path.home() / ".polymarket-bot" / "config"
        
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # Configuration file paths
        self.config_file = self.config_dir / "config.yaml"
        self.secrets_file = self.config_dir / "secrets.yaml"
        self.backup_dir = self.config_dir / "backups"
        self.backup_dir.mkdir(exist_ok=True)
        
        # Current configuration
        self.config: Optional[BotConfig] = None
        self.config_hash: Optional[str] = None
        
        # Environment variable prefix
        self.env_prefix = "POLYMARKET_BOT_"
        
        logger.info(f"Initialized ConfigManager with config directory: {self.config_dir}")
    
    def load_config(self, config_path: Optional[str] = None) -> BotConfig:
        """
        Load configuration from file.
        
        Args:
            config_path: Optional path to configuration file
            
        Returns:
            Loaded BotConfig
        """
        file_path = Path(config_path) if config_path else self.config_file
        
        logger.info(f"Loading configuration from {file_path}")
        
        # Default configuration
        default_config = self._create_default_config()
        
        # Load file configuration if exists
        file_config = {}
        if file_path.exists():
            try:
                if file_path.suffix.lower() in ['.yaml', '.yml']:
                    with open(file_path, 'r') as f:
                        file_config = yaml.safe_load(f) or {}
                elif file_path.suffix.lower() == '.json':
                    with open(file_path, 'r') as f:
                        file_config = json.load(f)
                else:
                    logger.warning(f"Unsupported config file format: {file_path.suffix}")
                    
            except Exception as e:
                logger.error(f"Error loading config file {file_path}: {e}")
                logger.info("Using default configuration")
        else:
            logger.info(f"Config file {file_path} not found, using defaults")
        
        # Load secrets if exists
        secrets_config = {}
        if self.secrets_file.exists():
            try:
                with open(self.secrets_file, 'r') as f:
                    secrets_config = yaml.safe_load(f) or {}
            except Exception as e:
                logger.error(f"Error loading secrets file: {e}")
        
        # Merge configurations (file config overrides defaults)
        merged_config = self._deep_merge(default_config.to_dict(), file_config)
        
        # Apply environment variables
        env_config = self._load_from_env()
        merged_config = self._deep_merge(merged_config, env_config)
        
        # Apply secrets
        merged_config = self._deep_merge(merged_config, secrets_config)
        
        # Create BotConfig instance
        self.config = BotConfig(**merged_config)
        
        # Validate configuration
        is_valid, errors = self.config.validate()
        if not is_valid:
            error_msg = "Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # Calculate config hash
        self.config_hash = self.config.get_config_hash()
        
        logger.info(f"Configuration loaded successfully (hash: {self.config_hash})")
        
        return self.config
    
    def _create_default_config(self) -> BotConfig:
        """Create default configuration."""
        return BotConfig(
            bot_name="Polymarket Trading Bot",
            version="1.0.0",
            environment="development",
            paper_trading=True,
            cycle_interval_minutes=60,
            enable_scheduler=True,
            
            market_filters={
                "min_liquidity_usd": 1000,
                "max_days_to_resolution": 90,
                "min_market_age_hours": 24,
                "min_daily_volume_usd": 100,
            },
            
            data_collection={
                "api_endpoint": "https://gamma-api.polymarket.com",
                "poll_interval_minutes": 5,
                "historical_days": 30,
                "cache_enabled": True,
                "cache_ttl_minutes": 10,
            },
            
            feature_engineering={
                "technical_indicators": {
                    "sma_periods": [12, 24, 48, 168],
                    "ema_periods": [6, 12, 24],
                    "rsi_period": 14,
                    "bb_period": 20,
                    "atr_period": 14,
                },
                "volume_indicators": {
                    "volume_sma_period": 24,
                    "volume_ema_period": 12,
                },
                "market_structure": {
                    "support_resistance_lookback": 168,
                    "trend_periods": [24, 72, 168],
                }
            },
            
            forecasting={
                "model_version": "google/timesfm-2.5-200m-pytorch",
                "forecast_horizon_hours": 24,
                "confidence_level": 0.95,
                "max_context_length": 1024,
                "normalize_inputs": True,
                "use_cache": True,
                "cache_ttl_minutes": 5,
            },
            
            signal_generation={
                "strategies": {
                    "probability_mispricing": {
                        "min_deviation": 0.02,
                        "confidence_threshold": 0.8,
                        "max_confidence_width": 0.05,
                        "volume_ratio_min": 1.2,
                    },
                    "convergence_trading": {
                        "min_deviation": 0.03,
                        "days_to_resolution_range": [7, 60],
                        "liquidity_score_min": 0.7,
                    }
                },
                "scoring_weights": {
                    "deviation_magnitude": 0.4,
                    "forecast_confidence": 0.3,
                    "market_liquidity": 0.15,
                    "time_to_resolution": 0.15,
                },
                "position_sizing": {
                    "base_size": 0.05,
                    "max_size": 0.10,
                    "min_size": 0.01,
                    "confidence_multiplier": 2.0,
                }
            },
            
            trade_execution={
                "paper_trading": True,
                "max_position_size_usd": 1000.0,
                "default_slippage": 0.001,
                "max_slippage": 0.01,
                "fee_percentage": 0.01,
                "min_fee_usd": 0.10,
                "order_timeout_seconds": 30,
                "retry_attempts": 3,
            },
            
            portfolio_management={
                "initial_capital": 10000.0,
                "max_position_size_pct": 0.10,
                "max_portfolio_risk": 0.20,
                "target_daily_return": 0.01,
                "stop_loss_pct": 0.05,
                "take_profit_pct": 0.10,
                "rebalance_threshold": 0.02,
            },
            
            risk_management={
                "max_portfolio_var_95_1d": 0.05,
                "max_drawdown_limit": 0.20,
                "max_concentration": 0.15,
                "min_liquidity_score": 0.5,
                "stop_loss_pct": 0.05,
                "take_profit_pct": 0.10,
                "trailing_stop_pct": 0.03,
                "var_confidence_level": 0.95,
                "var_time_horizon_days": 1,
            },
            
            performance_tracking={
                "performance_window_days": 30,
                "reporting_frequency": "daily",
                "generate_charts": True,
                "save_reports": True,
                "benchmark_returns": None,
                "risk_free_rate": 0.02,
            },
            
            logging_config={
                "level": "INFO",
                "file": "polymarket_bot.log",
                "max_file_size_mb": 100,
                "backup_count": 5,
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                "enable_console": True,
            }
        )
    
    def _deep_merge(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """
        Deep merge two dictionaries.
        
        Args:
            base: Base dictionary
            override: Override dictionary
            
        Returns:
            Merged dictionary
        """
        result = copy.deepcopy(base)
        
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        
        return result
    
    def _load_from_env(self) -> Dict[str, Any]:
        """Load configuration from environment variables."""
        env_config = {}
        
        # Helper function to convert string to appropriate type
        def parse_env_value(value: str):
            if value.lower() in ["true", "false"]:
                return value.lower() == "true"
            try:
                return int(value)
            except ValueError:
                try:
                    return float(value)
                except ValueError:
                    return value
        
        # Get all environment variables with prefix
        for env_key, env_value in os.environ.items():
            if env_key.startswith(self.env_prefix):
                # Remove prefix and convert to nested keys
                config_key = env_key[len(self.env_prefix):].lower()
                
                # Split by __ to create nested structure
                keys = config_key.split("__")
                
                # Navigate/create nested structure
                current = env_config
                for key in keys[:-1]:
                    if key not in current:
                        current[key] = {}
                    current = current[key]
                
                # Set value
                current[keys[-1]] = parse_env_value(env_value)
        
        return env_config
    
    def save_config(self, config: Optional[BotConfig] = None, backup: bool = True):
        """
        Save configuration to file.
        
        Args:
            config: Configuration to save (uses current if None)
            backup: Whether to create backup of existing config
        """
        if config is None:
            config = self.config
        
        if config is None:
            logger.error("No configuration to save")
            return
        
        # Validate before saving
        is_valid, errors = config.validate()
        if not is_valid:
            error_msg = "Cannot save invalid configuration:\n" + "\n".join(f"  - {e}" for e in errors)
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # Create backup if requested and file exists
        if backup and self.config_file.exists():
            backup_file = self.backup_dir / f"config_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.yaml"
            try:
                self.config_file.rename(backup_file)
                logger.info(f"Created config backup: {backup_file}")
            except Exception as e:
                logger.error(f"Error creating config backup: {e}")
        
        # Convert to dictionary
        config_dict = config.to_dict()
        
        # Separate secrets
        secrets_dict = config_dict.pop("api_credentials", {})
        
        # Save main configuration
        try:
            with open(self.config_file, 'w') as f:
                yaml.dump(config_dict, f, default_flow_style=False, indent=2)
            
            logger.info(f"Saved configuration to {self.config_file}")
            
        except Exception as e:
            logger.error(f"Error saving configuration: {e}")
            raise
        
        # Save secrets if any
        if secrets_dict:
            try:
                with open(self.secrets_file, 'w') as f:
                    yaml.dump(secrets_dict, f, default_flow_style=False, indent=2)
                
                # Set restrictive permissions on secrets file
                self.secrets_file.chmod(0o600)
                
                logger.info(f"Saved secrets to {self.secrets_file}")
                
            except Exception as e:
                logger.error(f"Error saving secrets: {e}")
                # Don't raise - main config is more important
        
        # Update current config and hash
        self.config = config
        self.config_hash = config.get_config_hash()
    
    def create_backup(self, description: str = "") -> str:
        """
        Create a configuration backup.
        
        Args:
            description: Optional description for backup
            
        Returns:
            Path to backup file
        """
        if self.config is None:
            logger.error("No configuration loaded, cannot create backup")
            return ""
        
        # Generate backup filename
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_name = f"config_backup_{timestamp}"
        
        if description:
            # Clean description for filename
            clean_desc = "".join(c for c in description if c.isalnum() or c in " _-")
            backup_name += f"_{clean_desc}"
        
        backup_file = self.backup_dir / f"{backup_name}.yaml"
        
        # Save backup
        try:
            config_dict = self.config.to_dict()
            
            # Add metadata
            config_dict["_backup_metadata"] = {
                "timestamp": datetime.utcnow().isoformat(),
                "description": description,
                "original_hash": self.config_hash,
                "version": self.config.version,
            }
            
            with open(backup_file, 'w') as f:
                yaml.dump(config_dict, f, default_flow_style=False, indent=2)
            
            logger.info(f"Created configuration backup: {backup_file}")
            
            return str(backup_file)
            
        except Exception as e:
            logger.error(f"Error creating configuration backup: {e}")
            return ""
    
    def restore_backup(self, backup_path: str) -> bool:
        """
        Restore configuration from backup.
        
        Args:
            backup_path: Path to backup file
            
        Returns:
            True if restore successful
        """
        try:
            backup_file = Path(backup_path)
            
            if not backup_file.exists():
                logger.error(f"Backup file not found: {backup_path}")
                return False
            
            # Load backup
            with open(backup_file, 'r') as f:
                backup_config = yaml.safe_load(f)
            
            # Remove backup metadata
            backup_config.pop("_backup_metadata", None)
            
            # Create BotConfig
            restored_config = BotConfig(**backup_config)
            
            # Save as current config
            self.save_config(restored_config, backup=True)
            
            logger.info(f"Restored configuration from backup: {backup_path}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error restoring configuration backup: {e}")
            return False
    
    def list_backups(self) -> List[Dict[str, Any]]:
        """
        List available configuration backups.
        
        Returns:
            List of backup information dictionaries
        """
        backups = []
        
        try:
            for backup_file in self.backup_dir.glob("*.yaml"):
                try:
                    with open(backup_file, 'r') as f:
                        backup_data = yaml.safe_load(f)
                    
                    metadata = backup_data.get("_backup_metadata", {})
                    
                    backups.append({
                        "file": str(backup_file),
                        "timestamp": metadata.get("timestamp", ""),
                        "description": metadata.get("description", ""),
                        "version": metadata.get("version", ""),
                        "size_kb": backup_file.stat().st_size / 1024,
                    })
                    
                except Exception as e:
                    logger.error(f"Error reading backup {backup_file}: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Error listing backups: {e}")
        
        # Sort by timestamp (newest first)
        backups.sort(key=lambda x: x["timestamp"], reverse=True)
        
        return backups
    
    def update_config(self, updates: Dict[str, Any]) -> BotConfig:
        """
        Update configuration with partial updates.
        
        Args:
            updates: Dictionary of configuration updates
            
        Returns:
            Updated BotConfig
        """
        if self.config is None:
            logger.error("No configuration loaded, cannot update")
            raise ValueError("Configuration not loaded")
        
        # Create copy of current config
        current_dict = self.config.to_dict()
        
        # Apply updates
        updated_dict = self._deep_merge(current_dict, updates)
        
        # Create new config
        new_config = BotConfig(**updated_dict)
        
        # Validate
        is_valid, errors = new_config.validate()
        if not is_valid:
            error_msg = "Configuration validation failed after update:\n" + "\n".join(f"  - {e}" for e in errors)
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # Save
        self.save_config(new_config, backup=True)
        
        logger.info(f"Configuration updated (new hash: {new_config.get_config_hash()})")
        
        return new_config
    
    def get_config_diff(self, other_config: BotConfig) -> Dict[str, Any]:
        """
        Get differences between current config and another config.
        
        Args:
            other_config: Configuration to compare
            
        Returns:
            Dictionary of differences
        """
        if self.config is None:
            logger.error("No configuration loaded, cannot diff")
            return {}
        
        current_dict = self.config.to_dict()
        other_dict = other_config.to_dict()
        
        diff = self._find_dict_diff(current_dict, other_dict)
        
        return diff
    
    def _find_dict_diff(self, dict1: Dict[str, Any], dict2: Dict[str, Any], path: str = "") -> Dict[str, Any]:
        """
        Find differences between two dictionaries.
        
        Args:
            dict1: First dictionary
            dict2: Second dictionary
            path: Current path for nested keys
            
        Returns:
            Dictionary of differences
        """
        diff = {}
        
        # Check keys in dict1 but not in dict2
        for key in set(dict1.keys()) - set(dict2.keys()):
            diff_key = f"{path}.{key}" if path else key
            diff[diff_key] = {"action": "removed", "old_value": dict1[key]}
        
        # Check keys in dict2 but not in dict1
        for key in set(dict2.keys()) - set(dict1.keys()):
            diff_key = f"{path}.{key}" if path else key
            diff[diff_key] = {"action": "added", "new_value": dict2[key]}
        
        # Check common keys
        for key in set(dict1.keys()) & set(dict2.keys()):
            val1 = dict1[key]
            val2 = dict2[key]
            
            if isinstance(val1, dict) and isinstance(val2, dict):
                # Recurse into nested dictionaries
                nested_diff = self._find_dict_diff(val1, val2, f"{path}.{key}" if path else key)
                diff.update(nested_diff)
            elif val1 != val2:
                diff_key = f"{path}.{key}" if path else key
                diff[diff_key] = {
                    "action": "changed",
                    "old_value": val1,
                    "new_value": val2
                }
        
        return diff
    
    def get_config_summary(self) -> Dict[str, Any]:
        """
        Get configuration summary.
        
        Returns:
            Dictionary with configuration summary
        """
        if self.config is None:
            return {"error": "Configuration not loaded"}
        
        return {
            "basic": {
                "bot_name": self.config.bot_name,
                "version": self.config.version,
                "environment": self.config.environment,
                "paper_trading": self.config.paper_trading,
                "cycle_interval_minutes": self.config.cycle_interval_minutes,
            },
            "components": {
                "data_collection": bool(self.config.data_collection),
                "feature_engineering": bool(self.config.feature_engineering),
                "forecasting": bool(self.config.forecasting),
                "signal_generation": bool(self.config.signal_generation),
                "trade_execution": bool(self.config.trade_execution),
                "portfolio_management": bool(self.config.portfolio_management),
                "risk_management": bool(self.config.risk_management),
                "performance_tracking": bool(self.config.performance_tracking),
            },
            "status": {
                "config_file": str(self.config_file),
                "secrets_file": str(self.secrets_file),
                "config_hash": self.config_hash,
                "config_valid": True,  # Assuming if loaded, it's valid
            }
        }
    
    def migrate_config(self, target_version: str) -> bool:
        """
        Migrate configuration to target version.
        
        Args:
            target_version: Target version string (e.g., "1.1.0")
            
        Returns:
            True if migration successful
        """
        if self.config is None:
            logger.error("No configuration loaded, cannot migrate")
            return False
        
        current_version = self.config.version
        
        if current_version == target_version:
            logger.info(f"Configuration already at target version {target_version}")
            return True
        
        logger.info(f"Migrating configuration from {current_version} to {target_version}")
        
        # Define migration steps
        migrations = self._get_migration_steps(current_version, target_version)
        
        if not migrations:
            logger.warning(f"No migration path from {current_version} to {target_version}")
            return False
        
        # Apply migrations
        migrated_config = copy.deepcopy(self.config)
        
        for migration_step in migrations:
            try:
                migrated_config = migration_step(migrated_config)
                logger.debug(f"Applied migration step")
            except Exception as e:
                logger.error(f"Error applying migration step: {e}")
                return False
        
        # Update version
        migrated_config.version = target_version
        
        # Save migrated config
        self.save_config(migrated_config, backup=True)
        
        logger.info(f"Configuration migrated to version {target_version}")
        
        return True
    
    def _get_migration_steps(self, from_version: str, to_version: str) -> List[callable]:
        """
        Get migration steps between versions.
        
        Args:
            from_version: Source version
            to_version: Target version
            
        Returns:
            List of migration functions
        """
        # This would contain actual migration logic
        # For now, return empty list
        return []
    
    def export_config(self, format: str = "yaml") -> str:
        """
        Export configuration as string.
        
        Args:
            format: Export format ("yaml", "json")
            
        Returns:
            Configuration as string
        """
        if self.config is None:
            logger.error("No configuration loaded, cannot export")
            return ""
        
        config_dict = self.config.to_dict()
        
        try:
            if format.lower() == "json":
                return json.dumps(config_dict, indent=2)
            elif format.lower() in ["yaml", "yml"]:
                import yaml
                return yaml.dump(config_dict, default_flow_style=False)
            else:
                logger.error(f"Unsupported export format: {format}")
                return ""
        except Exception as e:
            logger.error(f"Error exporting configuration: {e}")
            return ""


if __name__ == "__main__":
    # Example usage
    import tempfile
    
    # Create temporary config directory
    with tempfile.TemporaryDirectory() as tmpdir:
        # Initialize config manager
        config_manager = ConfigManager(tmpdir)
        
        # Load default configuration
        config = config_manager.load_config()
        
        print("Default configuration loaded:")
        print(f"  Bot Name: {config.bot_name}")
        print(f"  Version: {config.version}")
        print(f"  Environment: {config.environment}")
        print(f"  Paper Trading: {config.paper_trading}")
        print(f"  Cycle Interval: {config.cycle_interval_minutes} minutes")
        
        # Get config summary
        summary = config_manager.get_config_summary()
        print(f"\nConfiguration Summary:")
        print(f"  Components enabled: {len([c for c in summary['components'].values() if c])}")
        print(f"  Config hash: {summary['status']['config_hash']}")
        
        # Update configuration
        print("\nUpdating configuration...")
        updated_config = config_manager.update_config({
            "bot_name": "My Polymarket Bot",
            "cycle_interval_minutes": 30,
        })
        
        print(f"Updated bot name: {updated_config.bot_name}")
        print(f"Updated cycle interval: {updated_config.cycle_interval_minutes} minutes")
        
        # Create backup
        backup_file = config_manager.create_backup("Test backup")
        if backup_file:
            print(f"\nCreated backup: {backup_file}")
        
        # List backups
        backups = config_manager.list_backups()
        print(f"\nAvailable backups: {len(backups)}")
        
        # Export config
        exported_yaml = config_manager.export_config("yaml")
        print(f"\nExported config (first 500 chars):")
        print(exported_yaml[:500])
        
        print("\nConfiguration manager test completed")