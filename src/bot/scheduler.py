"""
Scheduler module for Polymarket Trading Bot.

This module handles:
- Scheduled task execution
- Cycle timing and coordination
- Error handling and retry logic
- Performance monitoring
"""

import asyncio
import time
import logging
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import traceback

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Status of scheduled tasks."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TaskPriority(Enum):
    """Priority of scheduled tasks."""
    HIGH = 0
    MEDIUM = 1
    LOW = 2


@dataclass
class ScheduledTask:
    """Container for scheduled task."""
    task_id: str
    name: str
    function: Callable
    schedule_type: str  # "interval", "cron", "once"
    schedule_value: Any  # interval seconds or cron expression
    priority: TaskPriority
    enabled: bool = True
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    status: TaskStatus = TaskStatus.PENDING
    retry_count: int = 0
    max_retries: int = 3
    retry_delay: int = 60  # seconds
    timeout: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def update_next_run(self, current_time: datetime):
        """Calculate next run time based on schedule."""
        if not self.enabled:
            self.next_run = None
            return
        
        if self.schedule_type == "interval":
            if self.last_run:
                self.next_run = self.last_run + timedelta(seconds=self.schedule_value)
            else:
                self.next_run = current_time + timedelta(seconds=self.schedule_value)
        
        elif self.schedule_type == "cron":
            # Simplified cron implementation
            # In production, use a proper cron parser
            if self.last_run:
                # Add 1 minute for demonstration
                self.next_run = self.last_run + timedelta(minutes=1)
            else:
                self.next_run = current_time + timedelta(minutes=1)
        
        elif self.schedule_type == "once":
            if self.last_run:
                self.next_run = None  # Already run
            else:
                # Parse datetime from schedule_value
                try:
                    if isinstance(self.schedule_value, str):
                        self.next_run = datetime.fromisoformat(self.schedule_value)
                    elif isinstance(self.schedule_value, datetime):
                        self.next_run = self.schedule_value
                    else:
                        self.next_run = None
                except Exception:
                    self.next_run = None


class BotScheduler:
    """Scheduler for bot tasks."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize scheduler.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        
        # Scheduler configuration
        self.scheduler_config = {
            "check_interval_seconds": 10,
            "max_concurrent_tasks": 5,
            "enable_health_checks": True,
            "health_check_interval": 300,  # 5 minutes
            "task_timeout_default": 1800,  # 30 minutes
            "retry_exponential_backoff": True,
        }
        
        # Update with config if provided
        if "scheduler" in self.config:
            self.scheduler_config.update(self.config["scheduler"])
        
        # Task storage
        self.tasks: Dict[str, ScheduledTask] = {}
        self.task_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.running_tasks: Dict[str, asyncio.Task] = {}
        
        # Scheduler state
        self.running = False
        self.scheduler_task: Optional[asyncio.Task] = None
        self.health_check_task: Optional[asyncio.Task] = None
        
        # Performance metrics
        self.metrics = {
            "tasks_completed": 0,
            "tasks_failed": 0,
            "tasks_retried": 0,
            "total_execution_time": 0.0,
            "avg_execution_time": 0.0,
            "queue_size_history": [],
        }
        
        logger.info(f"Initialized BotScheduler with config: {self.scheduler_config}")
    
    def add_task(
        self,
        task_id: str,
        name: str,
        function: Callable,
        schedule_type: str,
        schedule_value: Any,
        priority: TaskPriority = TaskPriority.MEDIUM,
        enabled: bool = True,
        max_retries: int = 3,
        retry_delay: int = 60,
        timeout: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Add a task to the scheduler.
        
        Args:
            task_id: Unique task identifier
            name: Human-readable task name
            function: Async function to execute
            schedule_type: "interval", "cron", or "once"
            schedule_value: Interval seconds, cron expression, or datetime
            priority: Task priority
            enabled: Whether task is enabled
            max_retries: Maximum retry attempts
            retry_delay: Delay between retries (seconds)
            timeout: Task timeout in seconds
            metadata: Additional task metadata
            
        Returns:
            True if task added successfully
        """
        if task_id in self.tasks:
            logger.warning(f"Task {task_id} already exists, updating instead")
            return self.update_task(task_id, {
                "name": name,
                "function": function,
                "schedule_type": schedule_type,
                "schedule_value": schedule_value,
                "priority": priority,
                "enabled": enabled,
                "max_retries": max_retries,
                "retry_delay": retry_delay,
                "timeout": timeout,
                "metadata": metadata
            })
        
        # Validate schedule type
        if schedule_type not in ["interval", "cron", "once"]:
            logger.error(f"Invalid schedule type: {schedule_type}")
            return False
        
        # Create task
        task = ScheduledTask(
            task_id=task_id,
            name=name,
            function=function,
            schedule_type=schedule_type,
            schedule_value=schedule_value,
            priority=priority,
            enabled=enabled,
            max_retries=max_retries,
            retry_delay=retry_delay,
            timeout=timeout or self.scheduler_config["task_timeout_default"],
            metadata=metadata
        )
        
        # Calculate initial next run
        task.update_next_run(datetime.utcnow())
        
        # Store task
        self.tasks[task_id] = task
        
        logger.info(f"Added task {task_id} ({name}) with {schedule_type} schedule")
        
        return True
    
    def update_task(self, task_id: str, updates: Dict[str, Any]) -> bool:
        """
        Update an existing task.
        
        Args:
            task_id: Task identifier
            updates: Dictionary of updates
            
        Returns:
            True if task updated successfully
        """
        if task_id not in self.tasks:
            logger.error(f"Task {task_id} not found")
            return False
        
        task = self.tasks[task_id]
        
        # Apply updates
        for key, value in updates.items():
            if hasattr(task, key):
                setattr(task, key, value)
            elif key == "metadata":
                if task.metadata is None:
                    task.metadata = {}
                task.metadata.update(value)
        
        # Recalculate next run
        task.update_next_run(datetime.utcnow())
        
        logger.info(f"Updated task {task_id}")
        
        return True
    
    def remove_task(self, task_id: str) -> bool:
        """
        Remove a task from the scheduler.
        
        Args:
            task_id: Task identifier
            
        Returns:
            True if task removed successfully
        """
        if task_id not in self.tasks:
            logger.error(f"Task {task_id} not found")
            return False
        
        # Cancel if running
        if task_id in self.running_tasks:
            self.running_tasks[task_id].cancel()
            del self.running_tasks[task_id]
        
        # Remove from tasks
        del self.tasks[task_id]
        
        logger.info(f"Removed task {task_id}")
        
        return True
    
    def enable_task(self, task_id: str) -> bool:
        """Enable a task."""
        if task_id not in self.tasks:
            logger.error(f"Task {task_id} not found")
            return False
        
        self.tasks[task_id].enabled = True
        self.tasks[task_id].update_next_run(datetime.utcnow())
        
        logger.info(f"Enabled task {task_id}")
        
        return True
    
    def disable_task(self, task_id: str) -> bool:
        """Disable a task."""
        if task_id not in self.tasks:
            logger.error(f"Task {task_id} not found")
            return False
        
        self.tasks[task_id].enabled = False
        self.tasks[task_id].next_run = None
        
        logger.info(f"Disabled task {task_id}")
        
        return True
    
    def run_task_now(self, task_id: str) -> bool:
        """
        Run a task immediately.
        
        Args:
            task_id: Task identifier
            
        Returns:
            True if task started successfully
        """
        if task_id not in self.tasks:
            logger.error(f"Task {task_id} not found")
            return False
        
        task = self.tasks[task_id]
        
        # Add to queue with high priority
        asyncio.create_task(self._queue_task(task, immediate=True))
        
        logger.info(f"Scheduled immediate execution for task {task_id}")
        
        return True
    
    async def start(self):
        """Start the scheduler."""
        if self.running:
            logger.warning("Scheduler is already running")
            return
        
        logger.info("Starting BotScheduler...")
        self.running = True
        
        # Start scheduler loop
        self.scheduler_task = asyncio.create_task(self._scheduler_loop())
        
        # Start health check if enabled
        if self.scheduler_config["enable_health_checks"]:
            self.health_check_task = asyncio.create_task(self._health_check_loop())
        
        logger.info("BotScheduler started")
    
    async def stop(self):
        """Stop the scheduler."""
        if not self.running:
            logger.warning("Scheduler is not running")
            return
        
        logger.info("Stopping BotScheduler...")
        self.running = False
        
        # Cancel scheduler loop
        if self.scheduler_task:
            self.scheduler_task.cancel()
            try:
                await self.scheduler_task
            except asyncio.CancelledError:
                pass
        
        # Cancel health check
        if self.health_check_task:
            self.health_check_task.cancel()
            try:
                await self.health_check_task
            except asyncio.CancelledError:
                pass
        
        # Cancel running tasks
        for task_id, task in list(self.running_tasks.items()):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        self.running_tasks.clear()
        
        logger.info("BotScheduler stopped")
    
    async def _scheduler_loop(self):
        """Main scheduler loop."""
        logger.info("Scheduler loop started")
        
        try:
            while self.running:
                current_time = datetime.utcnow()
                
                # Check for tasks that need to run
                for task_id, task in self.tasks.items():
                    if (task.enabled and 
                        task.next_run and 
                        current_time >= task.next_run and
                        task.status != TaskStatus.RUNNING):
                        
                        # Add to queue
                        await self._queue_task(task)
                
                # Process queue if not at max concurrent tasks
                if len(self.running_tasks) < self.scheduler_config["max_concurrent_tasks"]:
                    await self._process_queue()
                
                # Update metrics
                self.metrics["queue_size_history"].append(self.task_queue.qsize())
                if len(self.metrics["queue_size_history"]) > 100:
                    self.metrics["queue_size_history"] = self.metrics["queue_size_history"][-100:]
                
                # Sleep until next check
                await asyncio.sleep(self.scheduler_config["check_interval_seconds"])
                
        except asyncio.CancelledError:
            logger.info("Scheduler loop cancelled")
            raise
        except Exception as e:
            logger.error(f"Error in scheduler loop: {e}")
            logger.error(traceback.format_exc())
    
    async def _process_queue(self):
        """Process tasks from the queue."""
        try:
            # Get next task from queue
            if not self.task_queue.empty():
                priority, task_id = await self.task_queue.get()
                
                if task_id in self.tasks:
                    task = self.tasks[task_id]
                    
                    # Start task execution
                    execution_task = asyncio.create_task(
                        self._execute_task(task)
                    )
                    
                    self.running_tasks[task_id] = execution_task
                    
                    # Set up cleanup
                    execution_task.add_done_callback(
                        lambda t: asyncio.create_task(self._task_completed(task_id, t))
                    )
                
                self.task_queue.task_done()
                
        except Exception as e:
            logger.error(f"Error processing queue: {e}")
            logger.error(traceback.format_exc())
    
    async def _queue_task(self, task: ScheduledTask, immediate: bool = False):
        """
        Queue a task for execution.
        
        Args:
            task: Task to queue
            immediate: Whether to queue immediately (bypass schedule)
        """
        try:
            # Calculate priority value (lower = higher priority)
            priority_value = task.priority.value
            
            if immediate:
                priority_value = -1  # Highest priority for immediate execution
            
            # Add to queue
            await self.task_queue.put((priority_value, task.task_id))
            
            if not immediate:
                # Update next run time
                task.update_next_run(datetime.utcnow())
            
            logger.debug(f"Queued task {task.task_id} with priority {priority_value}")
            
        except Exception as e:
            logger.error(f"Error queuing task {task.task_id}: {e}")
    
    async def _execute_task(self, task: ScheduledTask):
        """
        Execute a task with timeout and error handling.
        
        Args:
            task: Task to execute
        """
        task.status = TaskStatus.RUNNING
        task.last_run = datetime.utcnow()
        
        execution_start = time.time()
        
        logger.info(f"Executing task {task.task_id} ({task.name})")
        
        try:
            # Set timeout
            if task.timeout:
                # Execute with timeout
                result = await asyncio.wait_for(
                    task.function(),
                    timeout=task.timeout
                )
            else:
                # Execute without timeout
                result = await task.function()
            
            execution_time = time.time() - execution_start
            
            # Update metrics
            self.metrics["tasks_completed"] += 1
            self.metrics["total_execution_time"] += execution_time
            self.metrics["avg_execution_time"] = (
                self.metrics["total_execution_time"] / self.metrics["tasks_completed"]
            )
            
            # Update task status
            task.status = TaskStatus.COMPLETED
            task.retry_count = 0
            
            logger.info(f"Task {task.task_id} completed in {execution_time:.2f}s")
            
            # Call completion callback if defined
            if task.metadata and "completion_callback" in task.metadata:
                callback = task.metadata["completion_callback"]
                if callable(callback):
                    try:
                        callback(task, result)
                    except Exception as e:
                        logger.error(f"Error in task completion callback: {e}")
            
            return result
            
        except asyncio.TimeoutError:
            execution_time = time.time() - execution_start
            
            logger.error(f"Task {task.task_id} timed out after {execution_time:.2f}s")
            
            task.status = TaskStatus.FAILED
            
            # Handle retry
            await self._handle_task_retry(task, "timeout")
            
        except Exception as e:
            execution_time = time.time() - execution_start
            
            logger.error(f"Task {task.task_id} failed: {e}")
            logger.error(traceback.format_exc())
            
            task.status = TaskStatus.FAILED
            
            # Handle retry
            await self._handle_task_retry(task, str(e))
    
    async def _handle_task_retry(self, task: ScheduledTask, error_message: str):
        """
        Handle task retry logic.
        
        Args:
            task: Failed task
            error_message: Error message from failure
        """
        task.retry_count += 1
        
        if task.retry_count <= task.max_retries:
            # Schedule retry
            retry_delay = task.retry_delay
            
            if self.scheduler_config["retry_exponential_backoff"]:
                # Exponential backoff
                retry_delay = task.retry_delay * (2 ** (task.retry_count - 1))
            
            logger.info(f"Scheduling retry {task.retry_count}/{task.max_retries} "
                       f"for task {task.task_id} in {retry_delay}s")
            
            # Update task status
            task.status = TaskStatus.PENDING
            
            # Schedule retry
            retry_time = datetime.utcnow() + timedelta(seconds=retry_delay)
            task.next_run = retry_time
            
            # Update metrics
            self.metrics["tasks_retried"] += 1
            
            # Call error callback if defined
            if task.metadata and "error_callback" in task.metadata:
                callback = task.metadata["error_callback"]
                if callable(callback):
                    try:
                        callback(task, error_message, task.retry_count)
                    except Exception as e:
                        logger.error(f"Error in task error callback: {e}")
        else:
            # Max retries exceeded
            logger.error(f"Task {task.task_id} failed after {task.max_retries} retries")
            
            task.status = TaskStatus.FAILED
            task.next_run = None
            
            # Update metrics
            self.metrics["tasks_failed"] += 1
            
            # Call failure callback if defined
            if task.metadata and "failure_callback" in task.metadata:
                callback = task.metadata["failure_callback"]
                if callable(callback):
                    try:
                        callback(task, error_message)
                    except Exception as e:
                        logger.error(f"Error in task failure callback: {e}")
    
    async def _task_completed(self, task_id: str, execution_task: asyncio.Task):
        """
        Handle task completion cleanup.
        
        Args:
            task_id: Task identifier
            execution_task: Completed execution task
        """
        # Remove from running tasks
        if task_id in self.running_tasks:
            del self.running_tasks[task_id]
        
        # Update task status if needed
        if task_id in self.tasks:
            task = self.tasks[task_id]
            
            if execution_task.done() and not execution_task.cancelled():
                if execution_task.exception():
                    # Task failed but already handled in _execute_task
                    pass
                else:
                    # Task completed successfully
                    task.status = TaskStatus.COMPLETED
    
    async def _health_check_loop(self):
        """Health check loop for monitoring scheduler health."""
        logger.info("Health check loop started")
        
        try:
            while self.running:
                await asyncio.sleep(self.scheduler_config["health_check_interval"])
                
                # Perform health checks
                health_status = self._perform_health_check()
                
                if not health_status["healthy"]:
                    logger.warning(f"Scheduler health check failed: {health_status['issues']}")
                
                # Log metrics
                self._log_metrics()
                
        except asyncio.CancelledError:
            logger.info("Health check loop cancelled")
            raise
        except Exception as e:
            logger.error(f"Error in health check loop: {e}")
    
    def _perform_health_check(self) -> Dict[str, Any]:
        """
        Perform scheduler health check.
        
        Returns:
            Dictionary with health status
        """
        issues = []
        
        # Check running tasks
        if len(self.running_tasks) > self.scheduler_config["max_concurrent_tasks"]:
            issues.append(f"Too many concurrent tasks: {len(self.running_tasks)}")
        
        # Check queue size
        queue_size = self.task_queue.qsize()
        if queue_size > 20:
            issues.append(f"Large task queue: {queue_size}")
        
        # Check for stuck tasks
        current_time = datetime.utcnow()
        for task_id, task in self.tasks.items():
            if task.status == TaskStatus.RUNNING:
                if task.last_run and (current_time - task.last_run).total_seconds() > 3600:
                    issues.append(f"Task {task_id} seems stuck (running for >1 hour)")
        
        healthy = len(issues) == 0
        
        return {
            "healthy": healthy,
            "timestamp": datetime.utcnow().isoformat(),
            "issues": issues,
            "metrics": {
                "tasks_total": len(self.tasks),
                "tasks_running": len(self.running_tasks),
                "tasks_pending": self.task_queue.qsize(),
                "tasks_completed": self.metrics["tasks_completed"],
                "tasks_failed": self.metrics["tasks_failed"],
                "avg_execution_time": self.metrics["avg_execution_time"],
            }
        }
    
    def _log_metrics(self):
        """Log scheduler metrics."""
        logger.info(
            f"Scheduler metrics: "
            f"Tasks={len(self.tasks)}, "
            f"Running={len(self.running_tasks)}, "
            f"Queue={self.task_queue.qsize()}, "
            f"Completed={self.metrics['tasks_completed']}, "
            f"Failed={self.metrics['tasks_failed']}, "
            f"Avg Time={self.metrics['avg_execution_time']:.2f}s"
        )
    
    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Get status of a specific task.
        
        Args:
            task_id: Task identifier
            
        Returns:
            Task status dictionary or None if not found
        """
        if task_id not in self.tasks:
            return None
        
        task = self.tasks[task_id]
        
        return {
            "task_id": task.task_id,
            "name": task.name,
            "status": task.status.value,
            "enabled": task.enabled,
            "last_run": task.last_run.isoformat() if task.last_run else None,
            "next_run": task.next_run.isoformat() if task.next_run else None,
            "retry_count": task.retry_count,
            "max_retries": task.max_retries,
            "running": task_id in self.running_tasks,
        }
    
    def get_all_tasks(self) -> List[Dict[str, Any]]:
        """
        Get status of all tasks.
        
        Returns:
            List of task status dictionaries
        """
        tasks_status = []
        
        for task_id, task in self.tasks.items():
            tasks_status.append({
                "task_id": task.task_id,
                "name": task.name,
                "status": task.status.value,
                "enabled": task.enabled,
                "schedule_type": task.schedule_type,
                "last_run": task.last_run.isoformat() if task.last_run else None,
                "next_run": task.next_run.isoformat() if task.next_run else None,
                "running": task_id in self.running_tasks,
            })
        
        return tasks_status
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        Get scheduler metrics.
        
        Returns:
            Dictionary with scheduler metrics
        """
        return {
            "scheduler": {
                "running": self.running,
                "tasks_total": len(self.tasks),
                "tasks_enabled": sum(1 for t in self.tasks.values() if t.enabled),
                "tasks_running": len(self.running_tasks),
                "queue_size": self.task_queue.qsize(),
            },
            "performance": {
                "tasks_completed": self.metrics["tasks_completed"],
                "tasks_failed": self.metrics["tasks_failed"],
                "tasks_retried": self.metrics["tasks_retried"],
                "total_execution_time": self.metrics["total_execution_time"],
                "avg_execution_time": self.metrics["avg_execution_time"],
                "queue_size_history": self.metrics["queue_size_history"][-10:],
            },
            "health": self._perform_health_check(),
        }


if __name__ == "__main__":
    # Example usage
    import asyncio
    
    async def example_task(name: str, duration: int = 2):
        """Example task function."""
        print(f"Task {name} starting...")
        await asyncio.sleep(duration)
        print(f"Task {name} completed")
        return f"Result from {name}"
    
    async def test_scheduler():
        # Initialize scheduler
        scheduler = BotScheduler()
        
        # Add tasks
        scheduler.add_task(
            task_id="task_1",
            name="Quick Task",
            function=lambda: example_task("Quick", 1),
            schedule_type="interval",
            schedule_value=10,  # Every 10 seconds
            priority=TaskPriority.HIGH
        )
        
        scheduler.add_task(
            task_id="task_2",
            name="Slow Task",
            function=lambda: example_task("Slow", 5),
            schedule_type="interval",
            schedule_value=30,  # Every 30 seconds
            priority=TaskPriority.LOW
        )
        
        scheduler.add_task(
            task_id="task_3",
            name="One-time Task",
            function=lambda: example_task("One-time", 3),
            schedule_type="once",
            schedule_value=(datetime.utcnow() + timedelta(seconds=5)).isoformat(),
            priority=TaskPriority.MEDIUM
        )
        
        # Start scheduler
        await scheduler.start()
        
        # Run for 60 seconds
        print("Running scheduler for 60 seconds...")
        await asyncio.sleep(60)
        
        # Get metrics
        metrics = scheduler.get_metrics()
        print(f"\nScheduler metrics:")
        print(f"  Tasks completed: {metrics['performance']['tasks_completed']}")
        print(f"  Tasks failed: {metrics['performance']['tasks_failed']}")
        print(f"  Average execution time: {metrics['performance']['avg_execution_time']:.2f}s")
        
        # Get task status
        tasks = scheduler.get_all_tasks()
        print(f"\nTask status:")
        for task in tasks:
            print(f"  {task['name']}: {task['status']} (next: {task['next_run']})")
        
        # Stop scheduler
        await scheduler.stop()
        
        print("\nScheduler test completed")
    
    # Run test
    asyncio.run(test_scheduler())