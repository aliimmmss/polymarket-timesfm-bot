"""
Cache utilities for Polymarket Trading Bot.

This module provides caching functionality for API responses, forecasts, and other data.
"""

import hashlib
import json
import pickle
from typing import Dict, List, Optional, Any, Tuple, Union
from datetime import datetime, timedelta
from pathlib import Path
import logging
import time
from enum import Enum
import threading

logger = logging.getLogger(__name__)


class CachePolicy(Enum):
    """Cache policy enumeration."""
    NO_CACHE = "no_cache"
    SHORT_TERM = "short_term"  # 5 minutes
    MEDIUM_TERM = "medium_term"  # 1 hour
    LONG_TERM = "long_term"  # 24 hours
    PERMANENT = "permanent"  # Until manually cleared


class CacheEntry:
    """Cache entry container."""
    
    def __init__(
        self,
        key: str,
        value: Any,
        ttl_seconds: int,
        created_at: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize cache entry.
        
        Args:
            key: Cache key
            value: Cached value
            ttl_seconds: Time to live in seconds
            created_at: Creation timestamp (default: current time)
            metadata: Optional metadata
        """
        self.key = key
        self.value = value
        self.ttl_seconds = ttl_seconds
        self.created_at = created_at or datetime.utcnow()
        self.metadata = metadata or {}
        self.access_count = 0
        self.last_accessed = self.created_at
    
    def is_expired(self) -> bool:
        """Check if cache entry is expired."""
        if self.ttl_seconds <= 0:
            return False  # Permanent
        
        age = (datetime.utcnow() - self.created_at).total_seconds()
        return age > self.ttl_seconds
    
    def get_age(self) -> float:
        """Get age of cache entry in seconds."""
        return (datetime.utcnow() - self.created_at).total_seconds()
    
    def get_time_remaining(self) -> float:
        """Get time remaining until expiration in seconds."""
        if self.ttl_seconds <= 0:
            return float('inf')
        
        age = self.get_age()
        return max(0, self.ttl_seconds - age)
    
    def access(self) -> Any:
        """Record access and return value."""
        self.access_count += 1
        self.last_accessed = datetime.utcnow()
        return self.value
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "key": self.key,
            "value": self.value,
            "ttl_seconds": self.ttl_seconds,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CacheEntry':
        """Create from dictionary."""
        return cls(
            key=data["key"],
            value=data["value"],
            ttl_seconds=data["ttl_seconds"],
            created_at=datetime.fromisoformat(data["created_at"]),
            metadata=data.get("metadata", {}),
        )


class CacheManager:
    """Cache manager for Polymarket Trading Bot."""
    
    # Default TTL values for cache policies
    POLICY_TTL = {
        CachePolicy.NO_CACHE: 0,
        CachePolicy.SHORT_TERM: 300,      # 5 minutes
        CachePolicy.MEDIUM_TERM: 3600,    # 1 hour
        CachePolicy.LONG_TERM: 86400,     # 24 hours
        CachePolicy.PERMANENT: -1,        # Never expire
    }
    
    def __init__(
        self,
        max_size: int = 1000,
        eviction_policy: str = "lru",
        cache_dir: Optional[str] = None,
        enable_disk_cache: bool = False,
        cleanup_interval: int = 300  # 5 minutes
    ):
        """
        Initialize cache manager.
        
        Args:
            max_size: Maximum number of cache entries
            eviction_policy: Eviction policy ("lru", "lfu", "fifo")
            cache_dir: Directory for disk cache
            enable_disk_cache: Whether to use disk cache
            cleanup_interval: Cleanup interval in seconds
        """
        self.max_size = max_size
        self.eviction_policy = eviction_policy.lower()
        
        # In-memory cache
        self.cache: Dict[str, CacheEntry] = {}
        
        # Disk cache configuration
        self.enable_disk_cache = enable_disk_cache
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            self.cache_dir = Path.home() / ".polymarket-bot" / "cache"
        
        if enable_disk_cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Disk cache enabled at {self.cache_dir}")
        
        # Statistics
        self.stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "evictions": 0,
            "disk_reads": 0,
            "disk_writes": 0,
            "errors": 0,
        }
        
        # Cleanup thread
        self.cleanup_interval = cleanup_interval
        self._cleanup_thread = None
        self._stop_cleanup = threading.Event()
        
        # Thread safety
        self._lock = threading.RLock()
        
        logger.info(f"CacheManager initialized: max_size={max_size}, "
                   f"eviction_policy={eviction_policy}, disk_cache={enable_disk_cache}")
    
    def start_cleanup(self):
        """Start background cleanup thread."""
        if self._cleanup_thread is None:
            self._cleanup_thread = threading.Thread(
                target=self._cleanup_loop,
                daemon=True,
                name="CacheCleanup"
            )
            self._cleanup_thread.start()
            logger.info("Cache cleanup thread started")
    
    def stop_cleanup(self):
        """Stop background cleanup thread."""
        if self._cleanup_thread:
            self._stop_cleanup.set()
            self._cleanup_thread.join(timeout=5)
            self._cleanup_thread = None
            logger.info("Cache cleanup thread stopped")
    
    def _cleanup_loop(self):
        """Background cleanup loop."""
        while not self._stop_cleanup.is_set():
            try:
                self.cleanup_expired()
                time.sleep(self.cleanup_interval)
            except Exception as e:
                logger.error(f"Error in cache cleanup loop: {e}")
                time.sleep(60)  # Wait before retry
    
    def generate_key(self, *args, **kwargs) -> str:
        """
        Generate cache key from arguments.
        
        Args:
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            Cache key string
        """
        # Create string representation
        parts = []
        
        # Add positional arguments
        for arg in args:
            if isinstance(arg, (str, int, float, bool, type(None))):
                parts.append(str(arg))
            else:
                # For complex objects, use hash
                try:
                    parts.append(hashlib.md5(pickle.dumps(arg)).hexdigest()[:8])
                except Exception:
                    parts.append(hashlib.md5(str(arg).encode()).hexdigest()[:8])
        
        # Add keyword arguments
        if kwargs:
            sorted_kwargs = sorted(kwargs.items())
            for key, value in sorted_kwargs:
                if isinstance(value, (str, int, float, bool, type(None))):
                    parts.append(f"{key}={value}")
                else:
                    try:
                        parts.append(f"{key}={hashlib.md5(pickle.dumps(value)).hexdigest()[:8]}")
                    except Exception:
                        parts.append(f"{key}={hashlib.md5(str(value).encode()).hexdigest()[:8]}")
        
        # Combine and hash
        key_string = "|".join(parts)
        return hashlib.md5(key_string.encode()).hexdigest()
    
    def get(
        self,
        key: str,
        default: Any = None,
        policy: Optional[CachePolicy] = None
    ) -> Any:
        """
        Get value from cache.
        
        Args:
            key: Cache key
            default: Default value if not found
            policy: Cache policy (for logging)
            
        Returns:
            Cached value or default
        """
        with self._lock:
            # Check in-memory cache first
            if key in self.cache:
                entry = self.cache[key]
                
                if entry.is_expired():
                    # Expired, remove
                    del self.cache[key]
                    self.stats["misses"] += 1
                    logger.debug(f"Cache miss (expired): {key}")
                    return default
                
                # Valid entry
                value = entry.access()
                self.stats["hits"] += 1
                logger.debug(f"Cache hit: {key} (policy={policy})")
                return value
            
            # Check disk cache
            if self.enable_disk_cache:
                disk_value = self._get_from_disk(key)
                if disk_value is not None:
                    # Found in disk cache, load to memory
                    self.cache[key] = disk_value
                    value = disk_value.access()
                    self.stats["hits"] += 1
                    self.stats["disk_reads"] += 1
                    logger.debug(f"Disk cache hit: {key}")
                    return value
            
            # Not found
            self.stats["misses"] += 1
            logger.debug(f"Cache miss: {key}")
            return default
    
    def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: Optional[int] = None,
        policy: CachePolicy = CachePolicy.MEDIUM_TERM,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl_seconds: Time to live in seconds (overrides policy)
            policy: Cache policy
            metadata: Optional metadata
            
        Returns:
            True if successful
        """
        with self._lock:
            try:
                # Determine TTL
                if ttl_seconds is not None:
                    final_ttl = ttl_seconds
                else:
                    final_ttl = self.POLICY_TTL.get(policy, 3600)
                
                # Create cache entry
                entry = CacheEntry(
                    key=key,
                    value=value,
                    ttl_seconds=final_ttl,
                    metadata=metadata or {}
                )
                
                # Check if we need to evict
                if len(self.cache) >= self.max_size:
                    self._evict()
                
                # Store in memory
                self.cache[key] = entry
                self.stats["sets"] += 1
                
                # Store on disk if enabled
                if self.enable_disk_cache:
                    self._save_to_disk(entry)
                
                logger.debug(f"Cache set: {key} (ttl={final_ttl}s, policy={policy})")
                return True
                
            except Exception as e:
                self.stats["errors"] += 1
                logger.error(f"Error setting cache key {key}: {e}")
                return False
    
    def delete(self, key: str) -> bool:
        """
        Delete value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            True if deleted
        """
        with self._lock:
            try:
                # Remove from memory
                if key in self.cache:
                    del self.cache[key]
                
                # Remove from disk
                if self.enable_disk_cache:
                    self._delete_from_disk(key)
                
                logger.debug(f"Cache delete: {key}")
                return True
                
            except Exception as e:
                self.stats["errors"] += 1
                logger.error(f"Error deleting cache key {key}: {e}")
                return False
    
    def clear(self, pattern: Optional[str] = None) -> int:
        """
        Clear cache entries.
        
        Args:
            pattern: Optional pattern to match keys
            
        Returns:
            Number of entries cleared
        """
        with self._lock:
            count = 0
            
            # Clear from memory
            if pattern:
                keys_to_delete = [k for k in self.cache.keys() if pattern in k]
                for key in keys_to_delete:
                    del self.cache[key]
                    count += 1
            else:
                count = len(self.cache)
                self.cache.clear()
            
            # Clear from disk
            if self.enable_disk_cache:
                disk_count = self._clear_disk(pattern)
                count = max(count, disk_count)
            
            logger.info(f"Cache cleared: {count} entries")
            return count
    
    def cleanup_expired(self) -> int:
        """
        Clean up expired cache entries.
        
        Returns:
            Number of entries cleaned up
        """
        with self._lock:
            expired_keys = []
            
            # Find expired entries
            for key, entry in self.cache.items():
                if entry.is_expired():
                    expired_keys.append(key)
            
            # Remove expired entries
            count = len(expired_keys)
            for key in expired_keys:
                del self.cache[key]
            
            # Clean up disk cache
            if self.enable_disk_cache:
                disk_count = self._cleanup_disk_expired()
                count += disk_count
            
            if count > 0:
                logger.debug(f"Cleaned up {count} expired cache entries")
            
            return count
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            hit_rate = 0
            if self.stats["hits"] + self.stats["misses"] > 0:
                hit_rate = self.stats["hits"] / (self.stats["hits"] + self.stats["misses"])
            
            return {
                "memory_entries": len(self.cache),
                "memory_size": sum(len(str(e.value)) for e in self.cache.values()),
                "hit_rate": hit_rate,
                "hits": self.stats["hits"],
                "misses": self.stats["misses"],
                "sets": self.stats["sets"],
                "evictions": self.stats["evictions"],
                "disk_reads": self.stats["disk_reads"],
                "disk_writes": self.stats["disk_writes"],
                "errors": self.stats["errors"],
                "max_size": self.max_size,
                "eviction_policy": self.eviction_policy,
            }
    
    def get_entries(self) -> List[Dict[str, Any]]:
        """Get list of all cache entries."""
        with self._lock:
            entries = []
            for key, entry in self.cache.items():
                entries.append({
                    "key": key,
                    "age_seconds": entry.get_age(),
                    "ttl_seconds": entry.ttl_seconds,
                    "time_remaining": entry.get_time_remaining(),
                    "access_count": entry.access_count,
                    "last_accessed": entry.last_accessed.isoformat(),
                    "metadata": entry.metadata,
                })
            
            return entries
    
    def _evict(self):
        """Evict entries based on eviction policy."""
        if not self.cache:
            return
        
        if self.eviction_policy == "lru":
            # Least Recently Used
            entries = sorted(
                self.cache.items(),
                key=lambda x: x[1].last_accessed
            )
        elif self.eviction_policy == "lfu":
            # Least Frequently Used
            entries = sorted(
                self.cache.items(),
                key=lambda x: x[1].access_count
            )
        elif self.eviction_policy == "fifo":
            # First In First Out
            entries = sorted(
                self.cache.items(),
                key=lambda x: x[1].created_at
            )
        else:
            # Default: random eviction
            import random
            entries = list(self.cache.items())
            random.shuffle(entries)
        
        # Evict oldest 10% or at least 1 entry
        evict_count = max(1, len(self.cache) // 10)
        
        for i in range(min(evict_count, len(entries))):
            key, entry = entries[i]
            del self.cache[key]
            self.stats["evictions"] += 1
        
        logger.debug(f"Evicted {evict_count} entries using {self.eviction_policy} policy")
    
    def _get_from_disk(self, key: str) -> Optional[CacheEntry]:
        """Get cache entry from disk."""
        try:
            filepath = self.cache_dir / f"{key}.cache"
            
            if not filepath.exists():
                return None
            
            # Check if file is too old (based on modification time)
            file_age = time.time() - filepath.stat().st_mtime
            if file_age > 86400:  # 1 day
                # File might be stale, delete it
                filepath.unlink(missing_ok=True)
                return None
            
            # Read file
            with open(filepath, 'rb') as f:
                data = pickle.load(f)
            
            # Create entry from data
            entry = CacheEntry.from_dict(data)
            
            # Check if expired
            if entry.is_expired():
                filepath.unlink(missing_ok=True)
                return None
            
            return entry
            
        except Exception as e:
            logger.error(f"Error reading cache from disk: {e}")
            return None
    
    def _save_to_disk(self, entry: CacheEntry):
        """Save cache entry to disk."""
        try:
            filepath = self.cache_dir / f"{entry.key}.cache"
            
            # Convert to dictionary
            data = entry.to_dict()
            
            # Save to file
            with open(filepath, 'wb') as f:
                pickle.dump(data, f)
            
            self.stats["disk_writes"] += 1
            
        except Exception as e:
            logger.error(f"Error saving cache to disk: {e}")
    
    def _delete_from_disk(self, key: str):
        """Delete cache entry from disk."""
        try:
            filepath = self.cache_dir / f"{key}.cache"
            if filepath.exists():
                filepath.unlink()
                
        except Exception as e:
            logger.error(f"Error deleting cache from disk: {e}")
    
    def _clear_disk(self, pattern: Optional[str] = None) -> int:
        """Clear disk cache."""
        try:
            count = 0
            
            if pattern:
                # Delete matching files
                for filepath in self.cache_dir.glob("*.cache"):
                    if pattern in filepath.stem:
                        filepath.unlink(missing_ok=True)
                        count += 1
            else:
                # Delete all cache files
                for filepath in self.cache_dir.glob("*.cache"):
                    filepath.unlink(missing_ok=True)
                    count += 1
            
            return count
            
        except Exception as e:
            logger.error(f"Error clearing disk cache: {e}")
            return 0
    
    def _cleanup_disk_expired(self) -> int:
        """Clean up expired disk cache entries."""
        try:
            count = 0
            current_time = datetime.utcnow()
            
            for filepath in self.cache_dir.glob("*.cache"):
                try:
                    # Read entry
                    with open(filepath, 'rb') as f:
                        data = pickle.load(f)
                    
                    # Check expiration
                    created_at = datetime.fromisoformat(data["created_at"])
                    ttl_seconds = data["ttl_seconds"]
                    
                    if ttl_seconds > 0:
                        age = (current_time - created_at).total_seconds()
                        if age > ttl_seconds:
                            # Expired
                            filepath.unlink(missing_ok=True)
                            count += 1
                    
                except Exception:
                    # Corrupted file, delete it
                    filepath.unlink(missing_ok=True)
                    count += 1
            
            return count
            
        except Exception as e:
            logger.error(f"Error cleaning up expired disk cache: {e}")
            return 0


# Convenience functions for common caching patterns
def cache_result(
    cache_manager: CacheManager,
    policy: CachePolicy = CachePolicy.MEDIUM_TERM,
    key_prefix: str = "",
    ttl_seconds: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None
):
    """
    Decorator to cache function results.
    
    Args:
        cache_manager: CacheManager instance
        policy: Cache policy
        key_prefix: Prefix for cache keys
        ttl_seconds: Custom TTL (overrides policy)
        metadata: Additional metadata
        
    Returns:
        Decorator function
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            # Generate cache key
            cache_key = cache_manager.generate_key(key_prefix, func.__name__, *args, **kwargs)
            
            # Try to get from cache
            cached_value = cache_manager.get(cache_key, policy=policy)
            if cached_value is not None:
                return cached_value
            
            # Call function
            result = func(*args, **kwargs)
            
            # Store in cache
            cache_manager.set(
                key=cache_key,
                value=result,
                ttl_seconds=ttl_seconds,
                policy=policy,
                metadata=metadata
            )
            
            return result
        
        return wrapper
    
    return decorator


if __name__ == "__main__":
    # Test CacheManager
    print("Testing CacheManager...")
    
    # Create cache manager
    cache = CacheManager(max_size=10, eviction_policy="lru")
    
    # Test basic operations
    print("\n1. Basic operations:")
    cache.set("key1", "value1", ttl_seconds=10)
    cache.set("key2", "value2", ttl_seconds=5)
    cache.set("key3", {"data": [1, 2, 3]}, ttl_seconds=60)
    
    print(f"   Get key1: {cache.get('key1')}")
    print(f"   Get key2: {cache.get('key2')}")
    print(f"   Get nonexistent: {cache.get('nonexistent', 'default')}")
    
    # Test statistics
    print("\n2. Statistics:")
    stats = cache.get_stats()
    print(f"   Hits: {stats['hits']}")
    print(f"   Misses: {stats['misses']}")
    print(f"   Hit rate: {stats['hit_rate']:.2%}")
    
    # Test expiration
    print("\n3. Expiration test:")
    import time
    
    cache.set("short_lived", "I expire quickly", ttl_seconds=2)
    print(f"   Before sleep: {cache.get('short_lived')}")
    time.sleep(3)
    print(f"   After sleep: {cache.get('short_lived', 'EXPIRED')}")
    
    # Test cache decorator
    print("\n4. Cache decorator test:")
    
    @cache_result(cache, policy=CachePolicy.SHORT_TERM)
    def expensive_computation(x: int):
        print(f"   Computing for x={x}...")
        time.sleep(0.1)  # Simulate expensive computation
        return x * x
    
    print(f"   First call: {expensive_computation(5)}")
    print(f"   Second call (should be cached): {expensive_computation(5)}")
    print(f"   Different input: {expensive_computation(6)}")
    
    # Test eviction
    print("\n5. Eviction test:")
    # Fill cache beyond limit
    for i in range(15):
        cache.set(f"evict_test_{i}", f"value_{i}", ttl_seconds=60)
    
    print(f"   Cache size: {len(cache.cache)}")
    
    # Clean up
    cache.clear()
    print("\n6. Cache cleared")
    
    print("\nCacheManager test completed")