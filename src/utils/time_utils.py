"""
Time utilities for Polymarket Trading Bot.

This module provides time and date manipulation utilities.
"""

from datetime import datetime, timedelta, timezone, date, time
from typing import Dict, List, Optional, Tuple, Union
import time as time_module
import calendar
from dateutil import parser
from dateutil.relativedelta import relativedelta
import pytz
import numpy as np
import logging

logger = logging.getLogger(__name__)


class TimeUtils:
    """Utility class for time operations."""
    
    # Default timezone (UTC)
    UTC = timezone.utc
    
    # Market hours (simplified - Polymarket operates 24/7 but US markets have patterns)
    MARKET_HOURS = {
        "US_OPEN": time(9, 30),  # 9:30 AM ET
        "US_CLOSE": time(16, 0),  # 4:00 PM ET
    }
    
    @staticmethod
    def now() -> datetime:
        """
        Get current UTC datetime.
        
        Returns:
            Current datetime in UTC
        """
        return datetime.now(TimeUtils.UTC)
    
    @staticmethod
    def to_utc(dt: datetime) -> datetime:
        """
        Convert datetime to UTC.
        
        Args:
            dt: Datetime to convert
            
        Returns:
            Datetime in UTC
        """
        if dt.tzinfo is None:
            # Naive datetime, assume UTC
            return dt.replace(tzinfo=TimeUtils.UTC)
        else:
            return dt.astimezone(TimeUtils.UTC)
    
    @staticmethod
    def from_timestamp(timestamp: Union[int, float]) -> datetime:
        """
        Convert timestamp to UTC datetime.
        
        Args:
            timestamp: Unix timestamp
            
        Returns:
            Datetime in UTC
        """
        return datetime.fromtimestamp(timestamp, TimeUtils.UTC)
    
    @staticmethod
    def to_timestamp(dt: datetime) -> float:
        """
        Convert datetime to Unix timestamp.
        
        Args:
            dt: Datetime to convert
            
        Returns:
            Unix timestamp
        """
        return dt.timestamp()
    
    @staticmethod
    def parse_datetime(
        datetime_str: str, 
        format: Optional[str] = None
    ) -> datetime:
        """
        Parse datetime string.
        
        Args:
            datetime_str: Datetime string
            format: Optional format string (uses dateutil.parser if None)
            
        Returns:
            Parsed datetime in UTC
        """
        if format:
            dt = datetime.strptime(datetime_str, format)
        else:
            dt = parser.parse(datetime_str)
        
        return TimeUtils.to_utc(dt)
    
    @staticmethod
    def format_datetime(
        dt: datetime, 
        format: str = "%Y-%m-%d %H:%M:%S UTC"
    ) -> str:
        """
        Format datetime to string.
        
        Args:
            dt: Datetime to format
            format: Format string
            
        Returns:
            Formatted datetime string
        """
        return dt.strftime(format)
    
    @staticmethod
    def time_ago(dt: datetime) -> str:
        """
        Get human-readable time ago string.
        
        Args:
            dt: Past datetime
            
        Returns:
            Human-readable string (e.g., "2 hours ago")
        """
        now = TimeUtils.now()
        diff = now - dt
        
        if diff.days > 365:
            years = diff.days // 365
            return f"{years} year{'s' if years > 1 else ''} ago"
        elif diff.days > 30:
            months = diff.days // 30
            return f"{months} month{'s' if months > 1 else ''} ago"
        elif diff.days > 0:
            return f"{diff.days} day{'s' if diff.days > 1 else ''} ago"
        elif diff.seconds > 3600:
            hours = diff.seconds // 3600
            return f"{hours} hour{'s' if hours > 1 else ''} ago"
        elif diff.seconds > 60:
            minutes = diff.seconds // 60
            return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
        else:
            return f"{diff.seconds} second{'s' if diff.seconds > 1 else ''} ago"
    
    @staticmethod
    def is_market_open(dt: Optional[datetime] = None) -> bool:
        """
        Check if US markets are open (simplified).
        
        Note: Polymarket operates 24/7, but this checks traditional market hours.
        
        Args:
            dt: Datetime to check (default: current time)
            
        Returns:
            True if markets are open
        """
        if dt is None:
            dt = TimeUtils.now()
        
        # Convert to US/Eastern time
        try:
            eastern = pytz.timezone("US/Eastern")
            dt_eastern = dt.astimezone(eastern)
        except Exception:
            # Fallback: assume dt is in US/Eastern
            dt_eastern = dt
        
        # Check if weekday
        if dt_eastern.weekday() >= 5:  # Saturday or Sunday
            return False
        
        # Check time
        dt_time = dt_eastern.time()
        open_time = TimeUtils.MARKET_HOURS["US_OPEN"]
        close_time = TimeUtils.MARKET_HOURS["US_CLOSE"]
        
        return open_time <= dt_time <= close_time
    
    @staticmethod
    def next_market_open(dt: Optional[datetime] = None) -> datetime:
        """
        Get next market open time.
        
        Args:
            dt: Starting datetime (default: current time)
            
        Returns:
            Next market open datetime in UTC
        """
        if dt is None:
            dt = TimeUtils.now()
        
        # Convert to US/Eastern
        try:
            eastern = pytz.timezone("US/Eastern")
            dt_eastern = dt.astimezone(eastern)
        except Exception:
            dt_eastern = dt
        
        # Get current date and time
        current_date = dt_eastern.date()
        current_time = dt_eastern.time()
        open_time = TimeUtils.MARKET_HOURS["US_OPEN"]
        
        # Check if market is already open today
        if (dt_eastern.weekday() < 5 and  # Weekday
            current_time >= open_time and  # After open
            current_time <= TimeUtils.MARKET_HOURS["US_CLOSE"]):  # Before close
            # Markets are open now
            next_open = datetime.combine(current_date, open_time)
        else:
            # Find next weekday
            days_to_add = 0
            while True:
                next_date = current_date + timedelta(days=days_to_add)
                if next_date.weekday() < 5:  # Weekday
                    break
                days_to_add += 1
            
            next_open = datetime.combine(next_date, open_time)
        
        # Convert to datetime with timezone
        next_open_eastern = eastern.localize(next_open)
        
        # Convert to UTC
        return next_open_eastern.astimezone(TimeUtils.UTC)
    
    @staticmethod
    def next_market_close(dt: Optional[datetime] = None) -> datetime:
        """
        Get next market close time.
        
        Args:
            dt: Starting datetime (default: current time)
            
        Returns:
            Next market close datetime in UTC
        """
        if dt is None:
            dt = TimeUtils.now()
        
        # Convert to US/Eastern
        try:
            eastern = pytz.timezone("US/Eastern")
            dt_eastern = dt.astimezone(eastern)
        except Exception:
            dt_eastern = dt
        
        # Get current date and time
        current_date = dt_eastern.date()
        current_time = dt_eastern.time()
        close_time = TimeUtils.MARKET_HOURS["US_CLOSE"]
        
        # Check if market is closed
        if (dt_eastern.weekday() >= 5 or  # Weekend
            current_time > close_time):  # After close
            # Market is closed, find next close (tomorrow if weekday)
            days_to_add = 1
            while True:
                next_date = current_date + timedelta(days=days_to_add)
                if next_date.weekday() < 5:  # Weekday
                    break
                days_to_add += 1
            
            next_close = datetime.combine(next_date, close_time)
        else:
            # Market is open, close is today
            next_close = datetime.combine(current_date, close_time)
        
        # Convert to datetime with timezone
        next_close_eastern = eastern.localize(next_close)
        
        # Convert to UTC
        return next_close_eastern.astimezone(TimeUtils.UTC)
    
    @staticmethod
    def get_market_hours_today() -> Optional[Tuple[datetime, datetime]]:
        """
        Get today's market open and close times.
        
        Returns:
            Tuple of (open_time, close_time) in UTC, or None if market closed today
        """
        now = TimeUtils.now()
        
        # Convert to US/Eastern
        try:
            eastern = pytz.timezone("US/Eastern")
            now_eastern = now.astimezone(eastern)
        except Exception:
            now_eastern = now
        
        # Check if today is a weekday
        if now_eastern.weekday() >= 5:  # Weekend
            return None
        
        # Get today's date
        today = now_eastern.date()
        
        # Create open and close times
        open_time = datetime.combine(today, TimeUtils.MARKET_HOURS["US_OPEN"])
        close_time = datetime.combine(today, TimeUtils.MARKET_HOURS["US_CLOSE"])
        
        # Convert to timezone-aware and UTC
        open_eastern = eastern.localize(open_time)
        close_eastern = eastern.localize(close_time)
        
        open_utc = open_eastern.astimezone(TimeUtils.UTC)
        close_utc = close_eastern.astimezone(TimeUtils.UTC)
        
        return open_utc, close_utc
    
    @staticmethod
    def time_until_next_interval(
        interval_minutes: int, 
        dt: Optional[datetime] = None
    ) -> timedelta:
        """
        Calculate time until next interval.
        
        Args:
            interval_minutes: Interval in minutes (e.g., 60 for hourly)
            dt: Starting datetime (default: current time)
            
        Returns:
            Time until next interval
        """
        if dt is None:
            dt = TimeUtils.now()
        
        # Calculate minutes past the hour
        minutes_past_hour = dt.minute + dt.second / 60 + dt.microsecond / 60_000_000
        
        # Calculate minutes until next interval
        minutes_to_next = interval_minutes - (minutes_past_hour % interval_minutes)
        
        # Create timedelta
        return timedelta(minutes=minutes_to_next)
    
    @staticmethod
    def round_to_interval(
        dt: datetime, 
        interval_minutes: int
    ) -> datetime:
        """
        Round datetime to nearest interval.
        
        Args:
            dt: Datetime to round
            interval_minutes: Interval in minutes
            
        Returns:
            Rounded datetime
        """
        # Calculate total minutes
        total_minutes = dt.hour * 60 + dt.minute
        rounded_minutes = (total_minutes // interval_minutes) * interval_minutes
        
        # Create new datetime
        rounded = dt.replace(
            hour=rounded_minutes // 60,
            minute=rounded_minutes % 60,
            second=0,
            microsecond=0
        )
        
        return rounded
    
    @staticmethod
    def generate_time_range(
        start: datetime,
        end: datetime,
        interval_minutes: int
    ) -> List[datetime]:
        """
        Generate list of datetimes at regular intervals.
        
        Args:
            start: Start datetime
            end: End datetime
            interval_minutes: Interval in minutes
            
        Returns:
            List of datetimes
        """
        if start > end:
            start, end = end, start
        
        result = []
        current = TimeUtils.round_to_interval(start, interval_minutes)
        
        while current <= end:
            result.append(current)
            current += timedelta(minutes=interval_minutes)
        
        return result
    
    @staticmethod
    def get_business_days_between(
        start: datetime,
        end: datetime,
        include_start: bool = True
    ) -> int:
        """
        Count business days (Monday-Friday) between two dates.
        
        Args:
            start: Start datetime
            end: End datetime
            include_start: Whether to include start day
            
        Returns:
            Number of business days
        """
        # Convert to dates
        start_date = start.date()
        end_date = end.date()
        
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        
        # Generate all days between
        all_days = np.arange(start_date, end_date + timedelta(days=1), dtype='datetime64[D]')
        
        # Convert to weekday numbers (Monday=0, Sunday=6)
        weekdays = np.array([d.astype(datetime).weekday() for d in all_days])
        
        # Count business days (Monday=0 to Friday=4)
        business_days = np.sum((weekdays >= 0) & (weekdays <= 4))
        
        # Adjust for include_start
        if not include_start and start_date <= end_date:
            business_days -= 1
        
        return max(0, business_days)
    
    @staticmethod
    def add_business_days(
        dt: datetime,
        days: int
    ) -> datetime:
        """
        Add business days to datetime.
        
        Args:
            dt: Starting datetime
            days: Number of business days to add
            
        Returns:
            Resulting datetime
        """
        if days == 0:
            return dt
        
        # Convert to date for calculation
        current_date = dt.date()
        
        # Add calendar days (approximation)
        calendar_days = days + (days // 5) * 2  # Account for weekends
        
        # Adjust forward or backward
        if days > 0:
            current_date += timedelta(days=calendar_days)
        else:
            current_date -= timedelta(days=abs(calendar_days))
        
        # Adjust for weekends
        while True:
            weekday = current_date.weekday()
            if weekday >= 5:  # Saturday or Sunday
                if days > 0:
                    current_date += timedelta(days=1)
                else:
                    current_date -= timedelta(days=1)
            else:
                break
        
        # Convert back to datetime
        result = datetime.combine(current_date, dt.time())
        if dt.tzinfo:
            result = result.replace(tzinfo=dt.tzinfo)
        
        return result
    
    @staticmethod
    def get_fiscal_quarter(date_obj: date) -> int:
        """
        Get fiscal quarter for date.
        
        Args:
            date_obj: Date
            
        Returns:
            Quarter number (1-4)
        """
        month = date_obj.month
        if month <= 3:
            return 1
        elif month <= 6:
            return 2
        elif month <= 9:
            return 3
        else:
            return 4
    
    @staticmethod
    def get_quarter_dates(year: int, quarter: int) -> Tuple[date, date]:
        """
        Get start and end dates for a quarter.
        
        Args:
            year: Year
            quarter: Quarter (1-4)
            
        Returns:
            Tuple of (start_date, end_date)
        """
        if quarter == 1:
            start_date = date(year, 1, 1)
            end_date = date(year, 3, 31)
        elif quarter == 2:
            start_date = date(year, 4, 1)
            end_date = date(year, 6, 30)
        elif quarter == 3:
            start_date = date(year, 7, 1)
            end_date = date(year, 9, 30)
        elif quarter == 4:
            start_date = date(year, 10, 1)
            end_date = date(year, 12, 31)
        else:
            raise ValueError(f"Invalid quarter: {quarter}")
        
        return start_date, end_date
    
    @staticmethod
    def get_last_day_of_month(year: int, month: int) -> date:
        """
        Get last day of month.
        
        Args:
            year: Year
            month: Month (1-12)
            
        Returns:
            Last day of month
        """
        _, last_day = calendar.monthrange(year, month)
        return date(year, month, last_day)
    
    @staticmethod
    def sleep_until(target_time: datetime):
        """
        Sleep until target time.
        
        Args:
            target_time: Time to sleep until
        """
        now = TimeUtils.now()
        
        if target_time > now:
            sleep_seconds = (target_time - now).total_seconds()
            logger.debug(f"Sleeping for {sleep_seconds:.1f} seconds")
            time_module.sleep(sleep_seconds)
    
    @staticmethod
    def format_duration(seconds: float) -> str:
        """
        Format duration in seconds to human-readable string.
        
        Args:
            seconds: Duration in seconds
            
        Returns:
            Formatted duration string
        """
        if seconds < 60:
            return f"{seconds:.1f}s"
        elif seconds < 3600:
            minutes = seconds / 60
            return f"{minutes:.1f}m"
        elif seconds < 86400:
            hours = seconds / 3600
            return f"{hours:.1f}h"
        else:
            days = seconds / 86400
            return f"{days:.1f}d"
    
    @staticmethod
    def calculate_time_weight(
        timestamps: List[datetime],
        decay_rate: float = 0.1,
        current_time: Optional[datetime] = None
    ) -> np.ndarray:
        """
        Calculate time-based weights for data points.
        
        Args:
            timestamps: List of timestamps
            decay_rate: Exponential decay rate (higher = faster decay)
            current_time: Reference time for decay (default: current time)
            
        Returns:
            Array of weights
        """
        if current_time is None:
            current_time = TimeUtils.now()
        
        # Calculate time differences in hours
        time_diffs = []
        for ts in timestamps:
            diff_hours = (current_time - ts).total_seconds() / 3600
            time_diffs.append(diff_hours)
        
        # Apply exponential decay
        weights = np.exp(-decay_rate * np.array(time_diffs))
        
        # Normalize to sum to 1
        if weights.sum() > 0:
            weights = weights / weights.sum()
        
        return weights
    
    @staticmethod
    def get_time_of_day_features(dt: datetime) -> Dict[str, float]:
        """
        Get features representing time of day.
        
        Args:
            dt: Datetime
            
        Returns:
            Dictionary of time features
        """
        # Circular encoding for periodic features
        hour = dt.hour + dt.minute / 60
        
        return {
            "hour_sin": np.sin(2 * np.pi * hour / 24),
            "hour_cos": np.cos(2 * np.pi * hour / 24),
            "minute_sin": np.sin(2 * np.pi * dt.minute / 60),
            "minute_cos": np.cos(2 * np.pi * dt.minute / 60),
            "second_sin": np.sin(2 * np.pi * dt.second / 60),
            "second_cos": np.cos(2 * np.pi * dt.second / 60),
            "is_night": 1.0 if 0 <= dt.hour < 6 else 0.0,
            "is_morning": 1.0 if 6 <= dt.hour < 12 else 0.0,
            "is_afternoon": 1.0 if 12 <= dt.hour < 18 else 0.0,
            "is_evening": 1.0 if 18 <= dt.hour < 24 else 0.0,
        }
    
    @staticmethod
    def get_date_features(date_obj: date) -> Dict[str, float]:
        """
        Get features representing date.
        
        Args:
            date_obj: Date
            
        Returns:
            Dictionary of date features
        """
        # Circular encoding for periodic features
        day_of_year = date_obj.timetuple().tm_yday
        day_of_month = date_obj.day
        month = date_obj.month
        
        return {
            "day_of_year_sin": np.sin(2 * np.pi * day_of_year / 365),
            "day_of_year_cos": np.cos(2 * np.pi * day_of_year / 365),
            "day_of_month_sin": np.sin(2 * np.pi * day_of_month / 31),
            "day_of_month_cos": np.cos(2 * np.pi * day_of_month / 31),
            "month_sin": np.sin(2 * np.pi * month / 12),
            "month_cos": np.cos(2 * np.pi * month / 12),
            "day_of_week": date_obj.weekday() / 6.0,  # Normalized 0-1
            "is_weekend": 1.0 if date_obj.weekday() >= 5 else 0.0,
            "quarter": TimeUtils.get_fiscal_quarter(date_obj) / 4.0,  # Normalized 0-1
        }


if __name__ == "__main__":
    # Test TimeUtils
    print("Testing TimeUtils...")
    
    # Current time
    now = TimeUtils.now()
    print(f"Current UTC time: {TimeUtils.format_datetime(now)}")
    
    # Time ago
    past_time = now - timedelta(hours=3, minutes=15)
    print(f"Time ago: {TimeUtils.time_ago(past_time)}")
    
    # Market hours
    print(f"Is market open? {TimeUtils.is_market_open()}")
    
    # Next market open/close
    next_open = TimeUtils.next_market_open()
    next_close = TimeUtils.next_market_close()
    print(f"Next market open: {TimeUtils.format_datetime(next_open)}")
    print(f"Next market close: {TimeUtils.format_datetime(next_close)}")
    
    # Time until next hourly interval
    time_until = TimeUtils.time_until_next_interval(60)
    print(f"Time until next hour: {time_until}")
    
    # Round to nearest 15 minutes
    rounded = TimeUtils.round_to_interval(now, 15)
    print(f"Rounded to 15min: {TimeUtils.format_datetime(rounded)}")
    
    # Business days calculation
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 1, 10)
    business_days = TimeUtils.get_business_days_between(start_date, end_date)
    print(f"Business days between {start_date.date()} and {end_date.date()}: {business_days}")
    
    # Add business days
    new_date = TimeUtils.add_business_days(now, 5)
    print(f"5 business days from now: {TimeUtils.format_datetime(new_date)}")
    
    # Quarter information
    qtr = TimeUtils.get_fiscal_quarter(now.date())
    print(f"Current quarter: Q{qtr}")
    
    # Duration formatting
    print(f"90 seconds: {TimeUtils.format_duration(90)}")
    print(f"7500 seconds: {TimeUtils.format_duration(7500)}")
    
    # Time features
    time_features = TimeUtils.get_time_of_day_features(now)
    print(f"Time features: {list(time_features.keys())}")
    
    date_features = TimeUtils.get_date_features(now.date())
    print(f"Date features: {list(date_features.keys())}")
    
    print("\nTimeUtils test completed")