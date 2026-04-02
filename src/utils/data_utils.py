"""
Data utilities for Polymarket Trading Bot.

This module provides data manipulation, transformation, and validation utilities.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple, Union
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class DataUtils:
    """Utility class for data operations."""
    
    @staticmethod
    def normalize_prices(prices: np.ndarray, method: str = "minmax") -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Normalize price data.
        
        Args:
            prices: Array of prices
            method: Normalization method ("minmax", "zscore", "log", "percent_change")
            
        Returns:
            Tuple of (normalized_prices, normalization_params)
        """
        if len(prices) == 0:
            return np.array([]), {}
        
        params = {"method": method}
        
        if method == "minmax":
            # Min-max normalization to [0, 1]
            min_val = np.min(prices)
            max_val = np.max(prices)
            
            if max_val - min_val > 0:
                normalized = (prices - min_val) / (max_val - min_val)
            else:
                normalized = np.zeros_like(prices)
            
            params.update({"min": float(min_val), "max": float(max_val)})
            
        elif method == "zscore":
            # Z-score normalization (mean=0, std=1)
            mean_val = np.mean(prices)
            std_val = np.std(prices)
            
            if std_val > 0:
                normalized = (prices - mean_val) / std_val
            else:
                normalized = np.zeros_like(prices)
            
            params.update({"mean": float(mean_val), "std": float(std_val)})
            
        elif method == "log":
            # Log normalization (handles only positive prices)
            if np.any(prices <= 0):
                logger.warning("Log normalization requires positive prices, using minmax instead")
                return DataUtils.normalize_prices(prices, "minmax")
            
            normalized = np.log(prices)
            params.update({"log_base": "e"})
            
        elif method == "percent_change":
            # Percentage change from first value
            if prices[0] > 0:
                normalized = (prices / prices[0] - 1) * 100
            else:
                normalized = np.zeros_like(prices)
            
            params.update({"base_value": float(prices[0])})
            
        else:
            logger.warning(f"Unknown normalization method: {method}, using minmax")
            return DataUtils.normalize_prices(prices, "minmax")
        
        return normalized, params
    
    @staticmethod
    def denormalize_prices(normalized: np.ndarray, params: Dict[str, Any]) -> np.ndarray:
        """
        Denormalize price data.
        
        Args:
            normalized: Normalized prices
            params: Normalization parameters from normalize_prices
            
        Returns:
            Denormalized prices
        """
        method = params.get("method", "minmax")
        
        if method == "minmax":
            min_val = params.get("min", 0)
            max_val = params.get("max", 1)
            return normalized * (max_val - min_val) + min_val
        
        elif method == "zscore":
            mean_val = params.get("mean", 0)
            std_val = params.get("std", 1)
            return normalized * std_val + mean_val
        
        elif method == "log":
            return np.exp(normalized)
        
        elif method == "percent_change":
            base_value = params.get("base_value", 1)
            return base_value * (1 + normalized / 100)
        
        else:
            logger.warning(f"Unknown normalization method for denormalization: {method}")
            return normalized
    
    @staticmethod
    def create_time_features(timestamps: List[datetime]) -> Dict[str, List[float]]:
        """
        Create time-based features from timestamps.
        
        Args:
            timestamps: List of datetime objects
            
        Returns:
            Dictionary of time features
        """
        if not timestamps:
            return {}
        
        features = {
            "hour_sin": [],
            "hour_cos": [],
            "day_sin": [],
            "day_cos": [],
            "month_sin": [],
            "month_cos": [],
            "day_of_week": [],
            "is_weekend": [],
            "is_market_hours": [],  # Assuming 9:30-16:00 ET
        }
        
        for ts in timestamps:
            # Circular encoding for periodic features
            hour = ts.hour
            features["hour_sin"].append(math.sin(2 * math.pi * hour / 24))
            features["hour_cos"].append(math.cos(2 * math.pi * hour / 24))
            
            day = ts.day
            features["day_sin"].append(math.sin(2 * math.pi * day / 31))
            features["day_cos"].append(math.cos(2 * math.pi * day / 31))
            
            month = ts.month
            features["month_sin"].append(math.sin(2 * math.pi * month / 12))
            features["month_cos"].append(math.cos(2 * math.pi * month / 12))
            
            # Day of week (0=Monday, 6=Sunday)
            dow = ts.weekday()
            features["day_of_week"].append(dow)
            features["is_weekend"].append(1 if dow >= 5 else 0)
            
            # Market hours (simplified: 9:30-16:00 ET = 14:30-21:00 UTC)
            hour_utc = ts.hour
            features["is_market_hours"].append(1 if 14 <= hour_utc <= 21 else 0)
        
        return features
    
    @staticmethod
    def calculate_returns(prices: np.ndarray, periods: List[int] = [1, 5, 10, 20]) -> Dict[str, np.ndarray]:
        """
        Calculate returns for different periods.
        
        Args:
            prices: Array of prices
            periods: List of periods for returns calculation
            
        Returns:
            Dictionary of returns for each period
        """
        returns = {}
        
        for period in periods:
            if period >= len(prices):
                continue
            
            # Calculate percentage returns
            returns_arr = np.zeros(len(prices))
            for i in range(period, len(prices)):
                if prices[i - period] > 0:
                    returns_arr[i] = (prices[i] / prices[i - period] - 1) * 100
            
            returns[f"return_{period}"] = returns_arr
        
        return returns
    
    @staticmethod
    def calculate_volatility(prices: np.ndarray, window: int = 20) -> np.ndarray:
        """
        Calculate rolling volatility.
        
        Args:
            prices: Array of prices
            window: Rolling window size
            
        Returns:
            Array of volatility values
        """
        if len(prices) < window:
            return np.zeros(len(prices))
        
        returns = np.diff(prices) / prices[:-1] * 100
        volatility = np.zeros(len(prices))
        
        for i in range(window, len(prices)):
            window_returns = returns[i-window:i]
            volatility[i] = np.std(window_returns)
        
        # Fill initial values with first calculated volatility
        if len(volatility) > window:
            volatility[:window] = volatility[window]
        
        return volatility
    
    @staticmethod
    def calculate_correlations(
        price_series: Dict[str, np.ndarray], 
        window: int = 50
    ) -> Dict[str, np.ndarray]:
        """
        Calculate rolling correlations between price series.
        
        Args:
            price_series: Dictionary of market_id -> price array
            window: Rolling window size
            
        Returns:
            Dictionary of correlation arrays
        """
        correlations = {}
        market_ids = list(price_series.keys())
        
        if len(market_ids) < 2:
            return correlations
        
        # Calculate returns for each series
        returns = {}
        for market_id, prices in price_series.items():
            if len(prices) > 1:
                returns[market_id] = np.diff(prices) / prices[:-1] * 100
        
        # Calculate pairwise correlations
        for i in range(len(market_ids)):
            for j in range(i + 1, len(market_ids)):
                id1 = market_ids[i]
                id2 = market_ids[j]
                
                if id1 in returns and id2 in returns:
                    ret1 = returns[id1]
                    ret2 = returns[id2]
                    
                    min_len = min(len(ret1), len(ret2))
                    if min_len < window:
                        continue
                    
                    # Calculate rolling correlation
                    corr = np.zeros(min_len)
                    for k in range(window, min_len):
                        window_ret1 = ret1[k-window:k]
                        window_ret2 = ret2[k-window:k]
                        corr[k] = np.corrcoef(window_ret1, window_ret2)[0, 1]
                    
                    # Fill initial values
                    corr[:window] = corr[window] if window < min_len else 0
                    
                    correlations[f"{id1}_{id2}_corr"] = corr
        
        return correlations
    
    @staticmethod
    def detect_anomalies(
        values: np.ndarray, 
        method: str = "iqr", 
        threshold: float = 3.0
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Detect anomalies in data.
        
        Args:
            values: Array of values
            method: Detection method ("iqr", "zscore", "mad")
            threshold: Detection threshold
            
        Returns:
            Tuple of (anomaly_mask, detection_stats)
        """
        if len(values) == 0:
            return np.array([], dtype=bool), {}
        
        stats = {"method": method, "threshold": threshold}
        
        if method == "iqr":
            # Interquartile Range method
            q1 = np.percentile(values, 25)
            q3 = np.percentile(values, 75)
            iqr = q3 - q1
            
            lower_bound = q1 - threshold * iqr
            upper_bound = q3 + threshold * iqr
            
            anomalies = (values < lower_bound) | (values > upper_bound)
            
            stats.update({
                "q1": float(q1),
                "q3": float(q3),
                "iqr": float(iqr),
                "lower_bound": float(lower_bound),
                "upper_bound": float(upper_bound),
            })
            
        elif method == "zscore":
            # Z-score method
            mean_val = np.mean(values)
            std_val = np.std(values)
            
            if std_val > 0:
                z_scores = np.abs((values - mean_val) / std_val)
                anomalies = z_scores > threshold
            else:
                anomalies = np.zeros_like(values, dtype=bool)
            
            stats.update({
                "mean": float(mean_val),
                "std": float(std_val),
            })
            
        elif method == "mad":
            # Median Absolute Deviation method
            median_val = np.median(values)
            mad = np.median(np.abs(values - median_val))
            
            if mad > 0:
                modified_z_scores = 0.6745 * np.abs(values - median_val) / mad
                anomalies = modified_z_scores > threshold
            else:
                anomalies = np.zeros_like(values, dtype=bool)
            
            stats.update({
                "median": float(median_val),
                "mad": float(mad),
            })
            
        else:
            logger.warning(f"Unknown anomaly detection method: {method}")
            anomalies = np.zeros_like(values, dtype=bool)
        
        stats.update({
            "total_values": len(values),
            "anomaly_count": int(np.sum(anomalies)),
            "anomaly_percentage": float(np.sum(anomalies) / len(values) * 100),
        })
        
        return anomalies, stats
    
    @staticmethod
    def fill_missing_values(
        values: np.ndarray, 
        method: str = "linear"
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Fill missing values (NaN) in data.
        
        Args:
            values: Array with potential NaN values
            method: Filling method ("linear", "forward", "backward", "mean", "median")
            
        Returns:
            Tuple of (filled_values, filling_stats)
        """
        if len(values) == 0:
            return np.array([]), {}
        
        # Create mask of missing values
        missing_mask = np.isnan(values)
        missing_count = np.sum(missing_mask)
        
        stats = {
            "method": method,
            "missing_count": int(missing_count),
            "missing_percentage": float(missing_count / len(values) * 100),
        }
        
        if missing_count == 0:
            return values.copy(), stats
        
        filled = values.copy()
        
        if method == "linear":
            # Linear interpolation
            indices = np.arange(len(filled))
            valid_mask = ~missing_mask
            
            if np.sum(valid_mask) >= 2:
                filled = np.interp(indices, indices[valid_mask], filled[valid_mask])
        
        elif method == "forward":
            # Forward fill
            for i in range(1, len(filled)):
                if np.isnan(filled[i]) and not np.isnan(filled[i-1]):
                    filled[i] = filled[i-1]
            
            # Handle leading NaNs
            for i in range(len(filled)-2, -1, -1):
                if np.isnan(filled[i]) and not np.isnan(filled[i+1]):
                    filled[i] = filled[i+1]
        
        elif method == "backward":
            # Backward fill
            for i in range(len(filled)-2, -1, -1):
                if np.isnan(filled[i]) and not np.isnan(filled[i+1]):
                    filled[i] = filled[i+1]
            
            # Handle trailing NaNs
            for i in range(1, len(filled)):
                if np.isnan(filled[i]) and not np.isnan(filled[i-1]):
                    filled[i] = filled[i-1]
        
        elif method == "mean":
            # Fill with mean of non-NaN values
            mean_val = np.nanmean(filled)
            filled[missing_mask] = mean_val
            stats["fill_value"] = float(mean_val)
        
        elif method == "median":
            # Fill with median of non-NaN values
            median_val = np.nanmedian(filled)
            filled[missing_mask] = median_val
            stats["fill_value"] = float(median_val)
        
        else:
            logger.warning(f"Unknown filling method: {method}, using linear")
            return DataUtils.fill_missing_values(values, "linear")
        
        # Verify no NaN remains
        final_missing = np.sum(np.isnan(filled))
        if final_missing > 0:
            logger.warning(f"{final_missing} NaN values remain after filling")
            # Fill remaining with mean
            mean_val = np.nanmean(filled)
            filled[np.isnan(filled)] = mean_val
        
        stats["final_missing_count"] = int(np.sum(np.isnan(filled)))
        
        return filled, stats
    
    @staticmethod
    def calculate_confidence_interval(
        values: np.ndarray, 
        confidence: float = 0.95
    ) -> Tuple[float, float, float]:
        """
        Calculate confidence interval for data.
        
        Args:
            values: Array of values
            confidence: Confidence level (0-1)
            
        Returns:
            Tuple of (mean, lower_bound, upper_bound)
        """
        if len(values) == 0:
            return 0.0, 0.0, 0.0
        
        mean_val = np.mean(values)
        std_val = np.std(values)
        n = len(values)
        
        if n < 2 or std_val == 0:
            return mean_val, mean_val, mean_val
        
        # Calculate critical value (using t-distribution for small n)
        from scipy import stats
        
        if n <= 30:
            # Use t-distribution for small samples
            critical_value = stats.t.ppf((1 + confidence) / 2, n - 1)
        else:
            # Use normal distribution for large samples
            critical_value = stats.norm.ppf((1 + confidence) / 2)
        
        margin_of_error = critical_value * std_val / np.sqrt(n)
        
        lower_bound = mean_val - margin_of_error
        upper_bound = mean_val + margin_of_error
        
        return float(mean_val), float(lower_bound), float(upper_bound)
    
    @staticmethod
    def resample_time_series(
        timestamps: List[datetime],
        values: List[float],
        freq: str = "1H",
        method: str = "mean"
    ) -> Tuple[List[datetime], List[float]]:
        """
        Resample time series to regular frequency.
        
        Args:
            timestamps: List of datetime objects
            values: List of corresponding values
            freq: Resampling frequency (e.g., "1H", "30min", "1D")
            method: Aggregation method ("mean", "median", "last", "first", "sum")
            
        Returns:
            Tuple of (resampled_timestamps, resampled_values)
        """
        if len(timestamps) != len(values):
            raise ValueError("timestamps and values must have same length")
        
        if len(timestamps) == 0:
            return [], []
        
        # Create DataFrame
        df = pd.DataFrame({
            "timestamp": timestamps,
            "value": values
        })
        
        df.set_index("timestamp", inplace=True)
        
        # Resample
        if method == "mean":
            resampled = df.resample(freq).mean()
        elif method == "median":
            resampled = df.resample(freq).median()
        elif method == "last":
            resampled = df.resample(freq).last()
        elif method == "first":
            resampled = df.resample(freq).first()
        elif method == "sum":
            resampled = df.resample(freq).sum()
        else:
            logger.warning(f"Unknown resampling method: {method}, using mean")
            resampled = df.resample(freq).mean()
        
        # Handle NaN values (forward fill then backward fill)
        resampled = resampled.fillna(method="ffill").fillna(method="bfill")
        
        # Convert back to lists
        resampled_timestamps = resampled.index.to_list()
        resampled_values = resampled["value"].tolist()
        
        return resampled_timestamps, resampled_values
    
    @staticmethod
    def save_data_to_file(
        data: Dict[str, Any],
        filepath: str,
        format: str = "json"
    ) -> bool:
        """
        Save data to file.
        
        Args:
            data: Data dictionary
            filepath: Path to save file
            format: File format ("json", "csv", "parquet")
            
        Returns:
            True if successful
        """
        try:
            path = Path(filepath)
            path.parent.mkdir(parents=True, exist_ok=True)
            
            if format == "json":
                with open(filepath, 'w') as f:
                    json.dump(data, f, indent=2, default=str)
            
            elif format == "csv":
                # Convert to DataFrame if possible
                if isinstance(data, dict):
                    # Simple dict to CSV (flatten if needed)
                    df = pd.DataFrame([data])
                    df.to_csv(filepath, index=False)
                elif isinstance(data, list):
                    df = pd.DataFrame(data)
                    df.to_csv(filepath, index=False)
                else:
                    logger.error(f"Cannot convert {type(data)} to CSV")
                    return False
            
            elif format == "parquet":
                # Convert to DataFrame if possible
                if isinstance(data, dict):
                    df = pd.DataFrame([data])
                elif isinstance(data, list):
                    df = pd.DataFrame(data)
                else:
                    logger.error(f"Cannot convert {type(data)} to Parquet")
                    return False
                
                df.to_parquet(filepath, index=False)
            
            else:
                logger.error(f"Unsupported format: {format}")
                return False
            
            logger.debug(f"Saved data to {filepath} ({format})")
            return True
            
        except Exception as e:
            logger.error(f"Error saving data to {filepath}: {e}")
            return False
    
    @staticmethod
    def load_data_from_file(
        filepath: str,
        format: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Load data from file.
        
        Args:
            filepath: Path to file
            format: File format (auto-detected if None)
            
        Returns:
            Loaded data or None if error
        """
        try:
            path = Path(filepath)
            
            if not path.exists():
                logger.error(f"File not found: {filepath}")
                return None
            
            # Auto-detect format
            if format is None:
                suffix = path.suffix.lower()
                if suffix == ".json":
                    format = "json"
                elif suffix == ".csv":
                    format = "csv"
                elif suffix in [".parquet", ".pq"]:
                    format = "parquet"
                else:
                    logger.error(f"Cannot auto-detect format for {filepath}")
                    return None
            
            if format == "json":
                with open(filepath, 'r') as f:
                    data = json.load(f)
            
            elif format == "csv":
                df = pd.read_csv(filepath)
                data = df.to_dict("records")
                if len(data) == 1:
                    data = data[0]  # Single row dict
            
            elif format == "parquet":
                df = pd.read_parquet(filepath)
                data = df.to_dict("records")
                if len(data) == 1:
                    data = data[0]  # Single row dict
            
            else:
                logger.error(f"Unsupported format: {format}")
                return None
            
            logger.debug(f"Loaded data from {filepath} ({format})")
            return data
            
        except Exception as e:
            logger.error(f"Error loading data from {filepath}: {e}")
            return None


if __name__ == "__main__":
    # Test DataUtils
    import numpy as np
    from datetime import datetime, timedelta
    
    # Generate test data
    timestamps = [datetime.now() - timedelta(hours=i) for i in range(100)]
    prices = np.random.randn(100).cumsum() + 100
    
    print("Testing DataUtils...")
    
    # Test normalization
    normalized, params = DataUtils.normalize_prices(prices, "minmax")
    print(f"Normalized prices shape: {normalized.shape}")
    print(f"Normalization params: {params}")
    
    # Test denormalization
    denormalized = DataUtils.denormalize_prices(normalized, params)
    print(f"Denormalization error: {np.max(np.abs(prices - denormalized)):.6f}")
    
    # Test time features
    time_features = DataUtils.create_time_features(timestamps[:10])
    print(f"Time features keys: {list(time_features.keys())}")
    
    # Test returns calculation
    returns = DataUtils.calculate_returns(prices, [1, 5, 10])
    print(f"Returns calculated for periods: {list(returns.keys())}")
    
    # Test volatility calculation
    volatility = DataUtils.calculate_volatility(prices, window=20)
    print(f"Volatility shape: {volatility.shape}")
    
    # Test anomaly detection
    anomalies, stats = DataUtils.detect_anomalies(prices, "iqr", 2.0)
    print(f"Anomalies detected: {np.sum(anomalies)} ({stats['anomaly_percentage']:.1f}%)")
    
    # Test missing value filling
    prices_with_nan = prices.copy()
    prices_with_nan[[10, 20, 30]] = np.nan
    filled, fill_stats = DataUtils.fill_missing_values(prices_with_nan, "linear")
    print(f"Missing values filled: {fill_stats['missing_count']} -> {fill_stats['final_missing_count']}")
    
    # Test confidence interval
    mean, lower, upper = DataUtils.calculate_confidence_interval(prices, 0.95)
    print(f"95% CI: {mean:.3f} [{lower:.3f}, {upper:.3f}]")
    
    # Test data saving/loading
    test_data = {
        "test_values": prices.tolist(),
        "test_timestamps": [ts.isoformat() for ts in timestamps[:10]],
        "test_metadata": {"source": "test"}
    }
    
    saved = DataUtils.save_data_to_file(test_data, "test_data.json", "json")
    if saved:
        loaded = DataUtils.load_data_from_file("test_data.json", "json")
        print(f"Data save/load successful: {loaded is not None}")
        
        # Clean up
        import os
        os.remove("test_data.json")
    
    print("\nDataUtils test completed")