"""
Logging utilities for Polymarket Trading Bot.

This module provides centralized logging setup and management.
"""

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
import json

# Global logger cache
_loggers = {}


def setup_logging(
    name: str = "polymarket_bot",
    level: str = "INFO",
    log_file: Optional[str] = None,
    log_dir: str = "logs",
    max_file_size_mb: int = 100,
    backup_count: int = 5,
    format_string: Optional[str] = None,
    enable_console: bool = True,
    enable_json: bool = False
) -> logging.Logger:
    """
    Set up logging for the application.
    
    Args:
        name: Logger name
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Log file name (default: {name}_{date}.log)
        log_dir: Directory for log files
        max_file_size_mb: Maximum log file size in MB
        backup_count: Number of backup files to keep
        format_string: Custom format string for logging
        enable_console: Whether to log to console
        enable_json: Whether to output logs in JSON format
        
    Returns:
        Configured logger instance
    """
    # Check if logger already exists
    if name in _loggers:
        return _loggers[name]
    
    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Clear any existing handlers
    logger.handlers.clear()
    
    # Create formatters
    if enable_json:
        formatter = JsonFormatter()
    else:
        if format_string is None:
            format_string = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        formatter = logging.Formatter(format_string)
    
    # Console handler
    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    # File handler
    if log_file:
        # Create log directory if it doesn't exist
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        
        # Create log file path
        if log_file == "auto":
            timestamp = datetime.now().strftime("%Y%m%d")
            log_file = f"{name}_{timestamp}.log"
        
        file_path = log_path / log_file
        
        # Create rotating file handler
        file_handler = logging.handlers.RotatingFileHandler(
            filename=file_path,
            maxBytes=max_file_size_mb * 1024 * 1024,  # Convert MB to bytes
            backupCount=backup_count,
            encoding='utf-8'
        )
        
        file_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    # Store logger in cache
    _loggers[name] = logger
    
    logger.info(f"Logging initialized: name={name}, level={level}, file={log_file}")
    
    return logger


def get_logger(name: str = "polymarket_bot") -> logging.Logger:
    """
    Get or create a logger by name.
    
    Args:
        name: Logger name
        
    Returns:
        Logger instance
    """
    if name in _loggers:
        return _loggers[name]
    
    # Create new logger with default settings
    return setup_logging(name)


class JsonFormatter(logging.Formatter):
    """JSON formatter for structured logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_entry = {
            "timestamp": self.formatTime(record, self.datefmt),
            "name": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "process": record.process,
            "thread": record.threadName,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        # Add extra attributes if present
        if hasattr(record, "extra"):
            log_entry.update(record.extra)
        
        return json.dumps(log_entry)


class StructuredLogger:
    """Wrapper for structured logging with context."""
    
    def __init__(self, name: str = "polymarket_bot", **context):
        """
        Initialize structured logger.
        
        Args:
            name: Logger name
            **context: Context variables to include in all logs
        """
        self.logger = get_logger(name)
        self.context = context
    
    def debug(self, message: str, **extra):
        """Log debug message with context."""
        self._log(logging.DEBUG, message, **extra)
    
    def info(self, message: str, **extra):
        """Log info message with context."""
        self._log(logging.INFO, message, **extra)
    
    def warning(self, message: str, **extra):
        """Log warning message with context."""
        self._log(logging.WARNING, message, **extra)
    
    def error(self, message: str, **extra):
        """Log error message with context."""
        self._log(logging.ERROR, message, **extra)
    
    def critical(self, message: str, **extra):
        """Log critical message with context."""
        self._log(logging.CRITICAL, message, **extra)
    
    def exception(self, message: str, exc_info: bool = True, **extra):
        """Log exception with context."""
        self._log(logging.ERROR, message, exc_info=exc_info, **extra)
    
    def _log(self, level: int, message: str, **extra):
        """Internal logging method."""
        # Combine context and extra fields
        log_fields = {**self.context, **extra}
        
        if isinstance(self.logger.handlers[0].formatter, JsonFormatter):
            # For JSON logging, add extra fields
            self.logger.log(level, message, extra={"extra": log_fields})
        else:
            # For regular logging, append context to message
            if log_fields:
                context_str = " ".join(f"{k}={v}" for k, v in log_fields.items())
                message = f"{message} [{context_str}]"
            self.logger.log(level, message)


# Convenience functions
def log_debug(message: str, **kwargs):
    """Convenience function for debug logging."""
    get_logger().debug(message, extra=kwargs)


def log_info(message: str, **kwargs):
    """Convenience function for info logging."""
    get_logger().info(message, extra=kwargs)


def log_warning(message: str, **kwargs):
    """Convenience function for warning logging."""
    get_logger().warning(message, extra=kwargs)


def log_error(message: str, **kwargs):
    """Convenience function for error logging."""
    get_logger().error(message, extra=kwargs)


def log_critical(message: str, **kwargs):
    """Convenience function for critical logging."""
    get_logger().critical(message, extra=kwargs)


def log_exception(message: str, **kwargs):
    """Convenience function for exception logging."""
    get_logger().exception(message, extra=kwargs)


if __name__ == "__main__":
    # Test logging setup
    logger = setup_logging(
        name="test_logger",
        level="DEBUG",
        log_file="test.log",
        enable_console=True
    )
    
    logger.debug("Debug message")
    logger.info("Info message")
    logger.warning("Warning message")
    logger.error("Error message")
    logger.critical("Critical message")
    
    # Test structured logging
    structured_logger = StructuredLogger(
        name="structured_test",
        user_id=123,
        session_id="abc123",
        component="test_component"
    )
    
    structured_logger.info("User action", action="click", target="button")
    structured_logger.error("Database error", query="SELECT * FROM users", error="connection_failed")
    
    print("Logging test completed")