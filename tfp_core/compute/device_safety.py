"""
Device Safety Guards for Compute Tasks

Monitors thermal, battery, and uptime conditions to prevent
consumer hardware degradation. Halts tasks if unsafe.
"""
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, List
from enum import Enum


class SafetyStatus(Enum):
    """Device safety status."""
    SAFE = "safe"
    WARNING = "warning"
    CRITICAL = "critical"
    HALT = "halt"


@dataclass
class DeviceMetrics:
    """Current device health metrics."""
    battery_level: int  # 0-100%
    is_charging: bool
    temperature_c: float  # Celsius
    cpu_load: float  # 0.0-1.0
    memory_load: float  # 0.0-1.0
    uptime_hours: float
    consecutive_tasks: int = 0
    last_task_time: Optional[float] = None


@dataclass
class SafetyCheckResult:
    """Result of a safety check."""
    status: SafetyStatus
    can_accept_task: bool
    should_halt_current: bool
    warnings: List[str]
    recommended_action: str


class DeviceSafetyGuard:
    """
    Safety guard for consumer devices participating in compute mesh.
    
    Ensures devices don't overheat, drain batteries, or degrade
    from excessive use.
    """
    
    # Default thresholds (configurable)
    DEFAULT_MIN_BATTERY = 30  # %
    DEFAULT_MAX_TEMP = 80  # Celsius
    DEFAULT_MAX_CPU_LOAD = 0.85  # 85%
    DEFAULT_MAX_MEMORY_LOAD = 0.90  # 90%
    DEFAULT_MAX_UPTIME_BEFORE_REST = 72  # Hours
    DEFAULT_MAX_CONSECUTIVE_TASKS = 10
    DEFAULT_COOLDOWN_BETWEEN_TASKS = 60  # Seconds
    
    def __init__(
        self,
        min_battery: int = DEFAULT_MIN_BATTERY,
        max_temp: float = DEFAULT_MAX_TEMP,
        max_cpu_load: float = DEFAULT_MAX_CPU_LOAD,
        max_memory_load: float = DEFAULT_MAX_MEMORY_LOAD,
        max_uptime_before_rest: float = DEFAULT_MAX_UPTIME_BEFORE_REST,
        max_consecutive_tasks: int = DEFAULT_MAX_CONSECUTIVE_TASKS,
        cooldown_between_tasks: float = DEFAULT_COOLDOWN_BETWEEN_TASKS
    ):
        self._min_battery = min_battery
        self._max_temp = max_temp
        self._max_cpu_load = max_cpu_load
        self._max_memory_load = max_memory_load
        self._max_uptime_before_rest = max_uptime_before_rest
        self._max_consecutive_tasks = max_consecutive_tasks
        self._cooldown_between_tasks = cooldown_between_tasks
        
        self._metrics_history: Dict[str, List[DeviceMetrics]] = {}
        self._active_tasks: Dict[str, float] = {}  # task_id -> start_time
        
    def check_safety(self, metrics: DeviceMetrics, device_id: str = "default") -> SafetyCheckResult:
        """
        Perform comprehensive safety check.
        
        Returns status and recommendations based on current metrics.
        """
        warnings = []
        status = SafetyStatus.SAFE
        can_accept = True
        should_halt = False
        
        # Battery check
        if metrics.battery_level < self._min_battery:
            if not metrics.is_charging:
                warnings.append(f"Battery low ({metrics.battery_level}%) and not charging")
                status = SafetyStatus.WARNING
                can_accept = False
        elif metrics.battery_level < self._min_battery + 10:
            warnings.append(f"Battery approaching minimum ({metrics.battery_level}%)")
            if status == SafetyStatus.SAFE:
                status = SafetyStatus.WARNING
        
        # Temperature check
        if metrics.temperature_c >= self._max_temp:
            warnings.append(f"Temperature critical ({metrics.temperature_c}°C)")
            status = SafetyStatus.CRITICAL
            should_halt = True
            can_accept = False
        elif metrics.temperature_c >= self._max_temp - 10:
            warnings.append(f"Temperature elevated ({metrics.temperature_c}°C)")
            if status == SafetyStatus.SAFE:
                status = SafetyStatus.WARNING
        
        # CPU load check
        if metrics.cpu_load >= self._max_cpu_load:
            warnings.append(f"CPU load too high ({metrics.cpu_load*100:.0f}%)")
            if status == SafetyStatus.SAFE:
                status = SafetyStatus.WARNING
            can_accept = False
        
        # Memory load check
        if metrics.memory_load >= self._max_memory_load:
            warnings.append(f"Memory load too high ({metrics.memory_load*100:.0f}%)")
            if status == SafetyStatus.SAFE:
                status = SafetyStatus.WARNING
            can_accept = False
        
        # Uptime check
        if metrics.uptime_hours >= self._max_uptime_before_rest:
            warnings.append(f"Extended uptime ({metrics.uptime_hours:.1f}h) - rest recommended")
            status = SafetyStatus.WARNING
            can_accept = False
        
        # Consecutive tasks check
        if metrics.consecutive_tasks >= self._max_consecutive_tasks:
            warnings.append(f"Too many consecutive tasks ({metrics.consecutive_tasks})")
            status = SafetyStatus.WARNING
            can_accept = False
        
        # Cooldown check
        if metrics.last_task_time is not None:
            time_since_last = time.time() - metrics.last_task_time
            if time_since_last < self._cooldown_between_tasks:
                remaining = self._cooldown_between_tasks - time_since_last
                warnings.append(f"Cooldown period active ({remaining:.0f}s remaining)")
                can_accept = False
        
        # Determine recommended action
        if should_halt:
            action = "HALT all compute tasks immediately"
        elif not can_accept:
            action = "Pause accepting new tasks"
        elif warnings:
            action = "Monitor closely, reduce task frequency"
        else:
            action = "Safe to proceed with compute tasks"
        
        # Record metrics
        if device_id not in self._metrics_history:
            self._metrics_history[device_id] = []
        self._metrics_history[device_id].append(metrics)
        
        # Keep only last 100 records per device
        if len(self._metrics_history[device_id]) > 100:
            self._metrics_history[device_id] = self._metrics_history[device_id][-100:]
        
        return SafetyCheckResult(
            status=status,
            can_accept_task=can_accept,
            should_halt_current=should_halt,
            warnings=warnings,
            recommended_action=action
        )
    
    def start_task(self, task_id: str, device_id: str = "default") -> bool:
        """Record that a task has started."""
        metrics_list = self._metrics_history.get(device_id, [])
        if not metrics_list:
            return False
            
        # Update last metrics
        latest = metrics_list[-1]
        latest.consecutive_tasks += 1
        latest.last_task_time = time.time()
        
        self._active_tasks[task_id] = time.time()
        return True
    
    def complete_task(self, task_id: str, device_id: str = "default") -> None:
        """Record that a task has completed."""
        if task_id in self._active_tasks:
            del self._active_tasks[task_id]
            
        # Reset consecutive counter after successful completion
        metrics_list = self._metrics_history.get(device_id, [])
        if metrics_list:
            # Don't reset immediately, let it decay naturally
            pass
    
    def get_active_task_count(self) -> int:
        """Get number of currently active tasks."""
        return len(self._active_tasks)
    
    def get_metrics_history(self, device_id: str = "default") -> List[DeviceMetrics]:
        """Get recent metrics history for a device."""
        return self._metrics_history.get(device_id, [])
    
    def update_thresholds(
        self,
        min_battery: Optional[int] = None,
        max_temp: Optional[float] = None,
        max_cpu_load: Optional[float] = None,
        max_memory_load: Optional[float] = None
    ) -> None:
        """Update safety thresholds."""
        if min_battery is not None:
            self._min_battery = min_battery
        if max_temp is not None:
            self._max_temp = max_temp
        if max_cpu_load is not None:
            self._max_cpu_load = max_cpu_load
        if max_memory_load is not None:
            self._max_memory_load = max_memory_load


def create_device_metrics(
    battery_level: int = 100,
    is_charging: bool = False,
    temperature_c: float = 45.0,
    cpu_load: float = 0.3,
    memory_load: float = 0.4,
    uptime_hours: float = 10.0,
    consecutive_tasks: int = 0
) -> DeviceMetrics:
    """Factory function to create DeviceMetrics."""
    return DeviceMetrics(
        battery_level=battery_level,
        is_charging=is_charging,
        temperature_c=temperature_c,
        cpu_load=cpu_load,
        memory_load=memory_load,
        uptime_hours=uptime_hours,
        consecutive_tasks=consecutive_tasks,
        last_task_time=None if consecutive_tasks == 0 else time.time() - 120
    )
