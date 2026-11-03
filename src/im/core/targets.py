"""Multi-target monitoring for im."""

import time
import threading
import json
import os
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from collections import defaultdict

from im.core import Monitor, SpeedTester, DeviceMonitor, Traffic, render
from im.platform import get_platform
from im.core.render import fmt_duration, fmt_speed, fmt_mb
from im.core.probes import ProbeType, ProbeResult
import copy


class TargetState(Enum):
    UP = "up"
    DOWN = "down"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


@dataclass
class TargetConfig:
    """Configuration for a monitoring target."""
    name: str
    host: str
    # Probe configuration
    probe_types: List[str] = field(default_factory=lambda: ['tcp', 'dns', 'http'])
    tcp_port: int = 443
    udp_port: int = 53
    http_path: str = "/"
    expected_status: int = 200
    # Thresholds
    max_latency_ms: Optional[float] = None
    max_loss_percent: Optional[float] = None
    min_download_mbps: Optional[float] = None
    min_upload_mbps: Optional[float] = None
    # Scheduling
    interval_seconds: float = 10.0
    timeout_seconds: float = 5.0
    # Metadata
    group: str = "default"
    tags: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'TargetConfig':
        return cls(**data)


@dataclass
class TargetStatus:
    """Current status of a target."""
    name: str
    state: TargetState = TargetState.UNKNOWN
    last_check: float = 0
    last_success: float = 0
    latency_ms: Optional[float] = None
    loss_percent: float = 0.0
    download_mbps: Optional[float] = None
    upload_mbps: Optional[float] = None
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_error: Optional[str] = None
    probe_results: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        d = asdict(self)
        d['state'] = self.state.value
        return d


@dataclass
class TargetGroup:
    """Group of related targets."""
    name: str
    targets: List[str] = field(default_factory=list)  # Target names
    # Aggregate thresholds
    max_latency_ms: Optional[float] = None
    max_loss_percent: Optional[float] = None
    # Aggregate state
    state: TargetState = TargetState.UNKNOWN
    up_count: int = 0
    down_count: int = 0
    degraded_count: int = 0
    
    def to_dict(self) -> dict:
        d = asdict(self)
        d['state'] = self.state.value
        return d


class DependencyGraph:
    """Manages target dependencies."""
    
    def __init__(self):
        self.dependencies: Dict[str, Set[str]] = defaultdict(set)  # target -> depends_on
        self.dependents: Dict[str, Set[str]] = defaultdict(set)   # target -> dependent_on
    
    def add_dependency(self, target: str, depends_on: str):
        """Add dependency: target depends on depends_on."""
        self.dependencies[target].add(depends_on)
        self.dependents[depends_on].add(target)
    
    def remove_dependency(self, target: str, depends_on: str):
        self.dependencies[target].discard(depends_on)
        self.dependents[depends_on].discard(target)
    
    def get_dependencies(self, target: str) -> Set[str]:
        return self.dependencies.get(target, set())
    
    def get_dependents(self, target: str) -> Set[str]:
        return self.dependents.get(target, set())
    
    def get_downstream_impact(self, failed_target: str) -> Set[str]:
        """Get all targets that would be impacted by a failure."""
        impacted = set()
        to_check = [failed_target]
        visited = set()
        
        while to_check:
            current = to_check.pop()
            if current in visited:
                continue
            visited.add(current)
            
            for dependent in self.dependents.get(current, set()):
                if dependent not in impacted:
                    impacted.add(dependent)
                    to_check.append(dependent)
        
        return impacted
    
    def has_cycle(self) -> bool:
        """Check for circular dependencies."""
        visited = set()
        rec_stack = set()
        
        def dfs(node):
            visited.add(node)
            rec_stack.add(node)
            
            for dep in self.dependencies.get(node, set()):
                if dep not in visited:
                    if dfs(dep):
                        return True
                elif dep in rec_stack:
                    return True
            
            rec_stack.remove(node)
            return False
        
        for node in self.dependencies:
            if node not in visited:
                if dfs(node):
                    return True
        return False


class TargetMonitor:
    """Monitors multiple targets with grouping and dependencies."""
    
    def __init__(self, config_dir: Optional[Path] = None):
        if config_dir is None:
            if os.name == 'nt':
                base = Path(os.environ.get('LOCALAPPDATA', Path.home()))
            else:
                base = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
            config_dir = base / 'im'
        
        self.config_dir = config_dir
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        self.targets_file = config_dir / 'targets.json'
        self.groups_file = config_dir / 'groups.json'
        
        self.targets: Dict[str, TargetConfig] = {}
        self.status: Dict[str, TargetStatus] = {}
        self.groups: Dict[str, TargetGroup] = {}
        self.dependency_graph = DependencyGraph()
        
        self._lock = threading.RLock()
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # Callbacks
        self.on_state_change: Optional[Callable[[str, TargetState, TargetState], None]] = None
        self.on_threshold_breach: Optional[Callable[[str, str, float, float], None]] = None
        
        # Probe manager
        from .probes import get_probe_manager
        self.probe_manager = get_probe_manager()
        
        self._load_config()
        self._initialize_status()
    
    def _load_config(self):
        """Load targets and groups from config files."""
        if self.targets_file.exists():
            try:
                with open(self.targets_file) as f:
                    data = json.load(f)
                    for t in data.get('targets', []):
                        tc = TargetConfig.from_dict(t)
                        self.targets[tc.name] = tc
            except Exception as e:
                print(f"Failed to load targets: {e}")
        
        if self.groups_file.exists():
            try:
                with open(self.groups_file) as f:
                    data = json.load(f)
                    for g in data.get('groups', []):
                        tg = TargetGroup(**g)
                        self.groups[g['name']] = tg
            except Exception as e:
                print(f"Failed to load groups: {e}")
    
    def _save_config(self):
        """Save targets and groups to config files."""
        try:
            with open(self.targets_file, 'w') as f:
                json.dump({'targets': [t.to_dict() for t in self.targets.values()]}, f, indent=2)
        except Exception as e:
            print(f"Failed to save targets: {e}")
        
        try:
            with open(self.groups_file, 'w') as f:
                json.dump({'groups': [g.to_dict() for g in self.groups.values()]}, f, indent=2)
        except Exception as e:
            print(f"Failed to save groups: {e}")
    
    def _initialize_status(self):
        """Initialize status for all targets."""
        with self._lock:
            for name, config in self.targets.items():
                if name not in self.status:
                    self.status[name] = TargetStatus(name=name)
    
    # Target management
    def add_target(self, config: TargetConfig) -> bool:
        """Add a new target."""
        with self._lock:
            if config.name in self.targets:
                return False
            self.targets[config.name] = config
            self.status[config.name] = TargetStatus(name=config.name)
            
            # Add to default group if no group specified
            if config.group and config.group not in self.groups:
                self.groups[config.group] = TargetGroup(name=config.group)
            if config.group:
                self.groups[config.group].targets.append(config.name)
            
            self._save_config()
            return True
    
    def remove_target(self, name: str) -> bool:
        """Remove a target."""
        with self._lock:
            if name not in self.targets:
                return False
            
            config = self.targets.pop(name)
            self.status.pop(name, None)
            
            # Remove from group
            if config.group and config.group in self.groups:
                if name in self.groups[config.group].targets:
                    self.groups[config.group].targets.remove(name)
            
            # Remove dependencies
            self.dependency_graph.dependencies.pop(name, None)
            self.dependency_graph.dependents.pop(name, None)
            
            self._save_config()
            return True
    
    def update_target(self, name: str, **kwargs) -> bool:
        """Update target configuration."""
        with self._lock:
            if name not in self.targets:
                return False
            
            config = self.targets[name]
            old_group = config.group
            
            for key, value in kwargs.items():
                if hasattr(config, key):
                    setattr(config, key, value)
            
            # Handle group change
            if 'group' in kwargs and kwargs['group'] != old_group:
                if old_group and old_group in self.groups:
                    if name in self.groups[old_group].targets:
                        self.groups[old_group].targets.remove(name)
                if config.group and config.group not in self.groups:
                    self.groups[config.group] = TargetGroup(name=config.group)
                if config.group:
                    self.groups[config.group].targets.append(name)
            
            self._save_config()
            return True
    
    def get_target(self, name: str) -> Optional[TargetConfig]:
        return self.targets.get(name)
    
    def list_targets(self, group: Optional[str] = None, enabled_only: bool = True) -> List[TargetConfig]:
        targets = list(self.targets.values())
        if enabled_only:
            targets = [t for t in targets if t.enabled]
        if group:
            targets = [t for t in targets if t.group == group]
        return targets
    
    # Group management
    def add_group(self, name: str, **kwargs) -> bool:
        with self._lock:
            if name in self.groups:
                return False
            self.groups[name] = TargetGroup(name=name, **kwargs)
            self._save_config()
            return True
    
    def remove_group(self, name: str) -> bool:
        with self._lock:
            if name not in self.groups:
                return False
            # Remove targets from group
            for target_name in self.groups[name].targets:
                if target_name in self.targets:
                    self.targets[target_name].group = "default"
            self.groups.pop(name)
            self._save_config()
            return True
    
    def get_group(self, name: str) -> Optional[TargetGroup]:
        return self.groups.get(name)
    
    def list_groups(self) -> List[TargetGroup]:
        return list(self.groups.values())
    
    # Dependency management
    def add_dependency(self, target: str, depends_on: str) -> bool:
        """Add dependency: target depends on depends_on."""
        with self._lock:
            if target not in self.targets or depends_on not in self.targets:
                return False
            self.dependency_graph.add_dependency(target, depends_on)
            if self.dependency_graph.has_cycle():
                self.dependency_graph.remove_dependency(target, depends_on)
                return False
            return True
    
    def remove_dependency(self, target: str, depends_on: str):
        self.dependency_graph.remove_dependency(target, depends_on)
    
    def get_dependencies(self, target: str) -> Set[str]:
        return self.dependency_graph.get_dependencies(target)
    
    def get_dependents(self, target: str) -> Set[str]:
        return self.dependency_graph.get_dependents(target)
    
    def get_impacted_targets(self, failed_target: str) -> Set[str]:
        """Get all targets impacted by a failure."""
        return self.dependency_graph.get_downstream_impact(failed_target)
    
    # Monitoring
    def start(self):
        """Start monitoring all enabled targets."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
    
    def stop(self):
        self._running = False
        self._stop_event.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=10)
    
    def _monitor_loop(self):
        """Main monitoring loop."""
        while not self._stop_event.is_set():
            start_time = time.time()
            
            # Get enabled targets
            with self._lock:
                enabled_targets = [
                    (name, config) for name, config in self.targets.items()
                    if config.enabled
                ]
            
            # Run checks in parallel
            for name, config in enabled_targets:
                if self._stop_event.is_set():
                    break
                self._check_target(name, config)
            
            # Update group states
            self._update_group_states()
            
            # Sleep until next interval
            elapsed = time.time() - start_time
            min_interval = min((c.interval_seconds for _, c in enabled_targets), default=10)
            sleep_time = max(0.1, min_interval - elapsed)
            self._stop_event.wait(sleep_time)
    
    def _check_target(self, name: str, config: TargetConfig):
        """Check a single target."""
        probe_types = []
        for pt in config.probe_types:
            try:
                probe_type = ProbeType(pt)
            except ValueError:
                continue
            probe_types.append(probe_type)
        
        if not probe_types:
            probe_types = [ProbeType.TCP, ProbeType.DNS, ProbeType.HTTP]
        
        # Run probes
        results = self.probe_manager.run_all(
            config.host,
            probe_types=probe_types,
            timeout=config.timeout_seconds
        )
        
        # Evaluate results
        old_status = self.status[name].state
        new_status, metrics = self._evaluate_results(results, config)
        
        with self._lock:
            status = self.status[name]
            old_state = status.state
            status.state = new_status
            status.last_check = time.time()
            status.probe_results = {pt.value: asdict(r) for pt, r in results.items()}
            
            # Update metrics
            latencies = [r.latency_ms for r in results.values() if r.success and r.latency_ms]
            if latencies:
                status.latency_ms = sum(latencies) / len(latencies)
            
            failed = sum(1 for r in results.values() if not r.success)
            total = len(results)
            status.loss_percent = (failed / total * 100) if total > 0 else 0
            
            # Extract speed metrics if available
            for pt, r in results.items():
                if r.metadata.get('download_mbps'):
                    status.download_mbps = r.metadata['download_mbps']
                if r.metadata.get('upload_mbps'):
                    status.upload_mbps = r.metadata['upload_mbps']
            
            if new_status == TargetState.UP:
                status.consecutive_successes += 1
                status.consecutive_failures = 0
                status.last_success = time.time()
                status.last_error = None
            else:
                status.consecutive_failures += 1
                status.consecutive_successes = 0
                # Collect errors
                errors = [r.error for r in results.values() if not r.success and r.error]
                status.last_error = '; '.join(errors) if errors else None
            
            # Check thresholds
            self._check_thresholds(name, config)
        
        # Notify state change
        if old_state != new_status and self.on_state_change:
            try:
                self.on_state_change(name, old_state, new_status)
            except Exception as e:
                print(f"State change callback error: {e}")
    
    def _evaluate_results(self, results: Dict[ProbeType, ProbeResult],
                          config: TargetConfig) -> Tuple[TargetState, Dict]:
        """Evaluate probe results against thresholds."""
        metrics = {}
        
        # Calculate aggregate metrics
        latencies = [r.latency_ms for r in results.values() if r.success and r.latency_ms]
        if latencies:
            metrics['avg_latency_ms'] = sum(latencies) / len(latencies)
            metrics['min_latency_ms'] = min(latencies)
            metrics['max_latency_ms'] = max(latencies)
        
        failed = sum(1 for r in results.values() if not r.success)
        total = len(results)
        metrics['loss_percent'] = (failed / total * 100) if total > 0 else 0
        
        # Determine state
        state = TargetState.UP
        
        # Check thresholds
        if config.max_latency_ms and metrics.get('avg_latency_ms', 0) > config.max_latency_ms:
            state = TargetState.DEGRADED
        
        if config.max_loss_percent and metrics.get('loss_percent', 0) > config.max_loss_percent:
            state = TargetState.DEGRADED
        
        if config.min_download_mbps:
            # Would need speed test results
            pass
        
        if config.min_upload_mbps:
            pass
        
        # If any critical probe failed, mark as DOWN
        critical_probes = [ProbeType.TCP, ProbeType.HTTP, ProbeType.DNS]
        critical_failed = any(
            not r.success and pt in critical_probes 
            for pt, r in results.items()
        )
        if critical_failed:
            state = TargetState.DOWN
        
        return state, metrics
    
    def _check_thresholds(self, name: str, config: TargetConfig):
        """Check if thresholds are breached."""
        status = self.status[name]
        
        if config.max_latency_ms and status.latency_ms:
            if status.latency_ms > config.max_latency_ms:
                if self.on_threshold_breach:
                    self.on_threshold_breach(name, 'latency', status.latency_ms, config.max_latency_ms)
        
        if config.max_loss_percent:
            if status.loss_percent > config.max_loss_percent:
                if self.on_threshold_breach:
                    self.on_threshold_breach(name, 'loss', status.loss_percent, config.max_loss_percent)
    
    def _update_group_states(self):
        """Update aggregate group states."""
        for group in self.groups.values():
            up = down = degraded = 0
            for target_name in group.targets:
                if target_name in self.status:
                    state = self.status[target_name].state
                    if state == TargetState.UP:
                        up += 1
                    elif state == TargetState.DOWN:
                        down += 1
                    elif state == TargetState.DEGRADED:
                        degraded += 1
            
            group.up_count = up
            group.down_count = down
            group.degraded_count = degraded
            
            # Determine group state
            if down > 0:
                group.state = TargetState.DOWN
            elif degraded > 0:
                group.state = TargetState.DEGRADED
            elif up > 0:
                group.state = TargetState.UP
            else:
                group.state = TargetState.UNKNOWN
    
    # Query methods
    def get_status(self, name: str) -> Optional[TargetStatus]:
        return self.status.get(name)
    
    def get_all_status(self) -> Dict[str, TargetStatus]:
        with self._lock:
            return copy.deepcopy(self.status)
    
    def get_group_status(self, name: str) -> Optional[TargetGroup]:
        return self.groups.get(name)
    
    def get_summary(self) -> Dict[str, Any]:
        """Get overall summary."""
        with self._lock:
            total = len(self.targets)
            up = sum(1 for s in self.status.values() if s.state == TargetState.UP)
            down = sum(1 for s in self.status.values() if s.state == TargetState.DOWN)
            degraded = sum(1 for s in self.status.values() if s.state == TargetState.DEGRADED)
            
            return {
                'total_targets': total,
                'up': up,
                'down': down,
                'degraded': degraded,
                'groups': {name: g.to_dict() for name, g in self.groups.items()},
                'targets': {name: s.to_dict() for name, s in self.status.items()},
            }
    
    def export_config(self) -> str:
        """Export all config as JSON."""
        data = {
            'targets': [t.to_dict() for t in self.targets.values()],
            'groups': [g.to_dict() for g in self.groups.values()],
        }
        return json.dumps(data, indent=2)
    
    def import_config(self, json_str: str) -> bool:
        try:
            data = json.loads(json_str)
            for t in data.get('targets', []):
                self.add_target(TargetConfig.from_dict(t))
            for g in data.get('groups', []):
                self.add_group(g['name'])
                if 'targets' in g:
                    self.groups[g['name']].targets = g['targets']
            return True
        except Exception as e:
            print(f"Failed to import config: {e}")
            return False


# Global instance
_target_monitor: Optional[TargetMonitor] = None


def get_target_monitor() -> TargetMonitor:
    global _target_monitor
    if _target_monitor is None:
        _target_monitor = TargetMonitor()
    return _target_monitor