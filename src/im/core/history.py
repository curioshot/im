"""Historical data storage and retrieval for im."""

import sqlite3
import os
import json
import csv
import io
import time
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Iterator
from dataclasses import dataclass, asdict
from collections import Counter
from queue import Queue
from contextlib import contextmanager
import gzip
import shutil


@dataclass
class CheckRecord:
    """Single connectivity check record."""
    timestamp: float
    up: bool
    latency_ms: Optional[float]
    probe_results: str  # JSON string


@dataclass
class SpeedRecord:
    """Speed test record."""
    timestamp: float
    download_mbps: Optional[float]
    upload_mbps: Optional[float]


@dataclass
class DeviceRecord:
    """Device discovery record."""
    timestamp: float
    ip: str
    mac: str
    hostname: Optional[str]
    state: str
    is_gateway: bool


@dataclass
class EventRecord:
    """State change event record."""
    timestamp: float
    event_type: str
    message: str


class HistoryManager:
    """Manages historical data storage with SQLite backend."""

    SCHEMA_VERSION = 1

    def __init__(self, data_dir: Optional[Path] = None):
        if data_dir is None:
            # Use XDG data directory
            if os.name == 'nt':  # Windows
                base = Path(os.environ.get('LOCALAPPDATA', Path.home()))
            else:
                base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share'))
            data_dir = base / 'im'
        
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.db_path = self.data_dir / 'history.db'
        self._lock = threading.Lock()
        self._write_queue = Queue()
        self._writer_thread = None
        self._stop_writer = threading.Event()
        
        self._init_db()
        self._start_writer()

    @contextmanager
    def _get_conn(self):
        """Get database connection with row factory."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        """Initialize database schema."""
        with self._get_conn() as conn:
            # Create schema version table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY
                )
            """)
            
            # Check current version
            cursor = conn.execute("SELECT version FROM schema_version")
            row = cursor.fetchone()
            current_version = row[0] if row else 0
            
            if current_version < self.SCHEMA_VERSION:
                self._migrate(conn, current_version)
                conn.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
                           (self.SCHEMA_VERSION,))
                conn.commit()

    def _migrate(self, conn: sqlite3.Connection, from_version: int):
        """Migrate database schema."""
        if from_version == 0:
            # Initial schema
            conn.executescript("""
                CREATE TABLE checks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    up INTEGER NOT NULL,
                    latency_ms REAL,
                    probe_results TEXT,
                    created_at REAL DEFAULT (strftime('%s', 'now'))
                );
                CREATE INDEX idx_checks_timestamp ON checks(timestamp);
                CREATE INDEX idx_checks_up ON checks(up);

                CREATE TABLE speed_tests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    download_mbps REAL,
                    upload_mbps REAL,
                    created_at REAL DEFAULT (strftime('%s', 'now'))
                );
                CREATE INDEX idx_speed_timestamp ON speed_tests(timestamp);

                CREATE TABLE devices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    ip TEXT NOT NULL,
                    mac TEXT NOT NULL,
                    hostname TEXT,
                    state TEXT NOT NULL,
                    is_gateway INTEGER NOT NULL,
                    created_at REAL DEFAULT (strftime('%s', 'now'))
                );
                CREATE INDEX idx_devices_timestamp ON devices(timestamp);
                CREATE INDEX idx_devices_ip ON devices(ip);

                CREATE TABLE events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at REAL DEFAULT (strftime('%s', 'now'))
                );
                CREATE INDEX idx_events_timestamp ON events(timestamp);
                CREATE INDEX idx_events_type ON events(event_type);
            """)

    def _start_writer(self):
        """Start background writer thread."""
        self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._writer_thread.start()

    def _writer_loop(self):
        """Background thread to batch write records."""
        batch = []
        batch_size = 50
        flush_interval = 5.0  # seconds
        last_flush = time.time()
        
        while not self._stop_writer.is_set():
            try:
                # Wait for items with timeout
                item = self._write_queue.get(timeout=1.0)
                batch.append(item)
                
                # Flush if batch full or interval elapsed
                now = time.time()
                if len(batch) >= batch_size or (now - last_flush) >= flush_interval:
                    self._flush_batch(batch)
                    batch.clear()
                    last_flush = now
                    
            except Exception:
                # Timeout or other error, continue
                if batch and (time.time() - last_flush) >= flush_interval:
                    self._flush_batch(batch)
                    batch.clear()
                    last_flush = time.time()
        
        # Flush remaining on shutdown
        if batch:
            self._flush_batch(batch)

    def _flush_batch(self, batch: List[tuple]):
        """Write batch of records to database."""
        if not batch:
            return
            
        with self._lock:
            with self._get_conn() as conn:
                for table, data in batch:
                    if table == 'checks':
                        placeholders = ','.join(['?'] * 4)
                        conn.execute(f"INSERT INTO {table} (timestamp, up, latency_ms, probe_results) VALUES ({placeholders})", data)
                    elif table == 'speed_tests':
                        placeholders = ','.join(['?'] * 3)
                        conn.execute(f"INSERT INTO {table} (timestamp, download_mbps, upload_mbps) VALUES ({placeholders})", data)
                    elif table == 'devices':
                        placeholders = ','.join(['?'] * 6)
                        conn.execute(f"INSERT INTO {table} (timestamp, ip, mac, hostname, state, is_gateway) VALUES ({placeholders})", data)
                    elif table == 'events':
                        placeholders = ','.join(['?'] * 3)
                        conn.execute(f"INSERT INTO {table} (timestamp, event_type, message) VALUES ({placeholders})", data)
                    else:
                        placeholders = ','.join(['?'] * len(data))
                        conn.execute(f"INSERT INTO {table} VALUES ({placeholders})", data)
                conn.commit()

    def record_check(self, up: bool, latency_ms: Optional[float], probe_results: Dict):
        """Record a connectivity check."""
        self._write_queue.put((
            'checks',
            (time.time(), int(up), latency_ms, json.dumps(probe_results))
        ))

    def record_speed(self, download_mbps: Optional[float], upload_mbps: Optional[float]):
        """Record a speed test result."""
        self._write_queue.put((
            'speed_tests',
            (time.time(), download_mbps, upload_mbps)
        ))

    def record_devices(self, devices: List[Dict]):
        """Record device discovery snapshot."""
        ts = time.time()
        for dev in devices:
            self._write_queue.put((
                'devices',
                (ts, dev.get('ip', ''), dev.get('mac', ''), 
                 dev.get('hostname'), dev.get('state', ''),
                 int(dev.get('is_gateway', False)))
            ))

    def record_event(self, event_type: str, message: str):
        """Record a state change event."""
        self._write_queue.put((
            'events',
            (time.time(), event_type, message)
        ))

    # Query methods
    def get_checks(self, since: Optional[float] = None, until: Optional[float] = None,
                   limit: int = 1000, up_only: bool = False) -> List[CheckRecord]:
        """Get connectivity checks."""
        query = "SELECT timestamp, up, latency_ms, probe_results FROM checks WHERE 1=1"
        params = []
        
        if since:
            query += " AND timestamp >= ?"
            params.append(since)
        if until:
            query += " AND timestamp <= ?"
            params.append(until)
        if up_only:
            query += " AND up = 1"
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [CheckRecord(r[0], bool(r[1]), r[2], r[3]) for r in rows]

    def get_speed_tests(self, since: Optional[float] = None, until: Optional[float] = None,
                        limit: int = 1000) -> List[SpeedRecord]:
        """Get speed test records."""
        query = "SELECT timestamp, download_mbps, upload_mbps FROM speed_tests WHERE 1=1"
        params = []
        
        if since:
            query += " AND timestamp >= ?"
            params.append(since)
        if until:
            query += " AND timestamp <= ?"
            params.append(until)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [SpeedRecord(r[0], r[1], r[2]) for r in rows]

    def get_devices(self, since: Optional[float] = None, until: Optional[float] = None,
                    limit: int = 1000) -> List[DeviceRecord]:
        """Get device records."""
        query = "SELECT timestamp, ip, mac, hostname, state, is_gateway FROM devices WHERE 1=1"
        params = []
        
        if since:
            query += " AND timestamp >= ?"
            params.append(since)
        if until:
            query += " AND timestamp <= ?"
            params.append(until)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [DeviceRecord(r[0], r[1], r[2], r[3], r[4], bool(r[5])) for r in rows]

    def get_events(self, since: Optional[float] = None, until: Optional[float] = None,
                   limit: int = 1000) -> List[EventRecord]:
        """Get event records."""
        query = "SELECT timestamp, event_type, message FROM events WHERE 1=1"
        params = []
        
        if since:
            query += " AND timestamp >= ?"
            params.append(since)
        if until:
            query += " AND timestamp <= ?"
            params.append(until)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [EventRecord(r[0], r[1], r[2]) for r in rows]

    def get_stats(self, since: Optional[float] = None) -> Dict[str, Any]:
        """Get summary statistics."""
        since_clause = "WHERE timestamp >= ?" if since else ""
        params = [since] if since else []
        
        with self._get_conn() as conn:
            stats = {}
            
            # Check stats
            row = conn.execute(f"""
                SELECT 
                    COUNT(*) as total, 
                    COALESCE(SUM(up), 0) as up_count,
                       COALESCE(AVG(latency_ms), 0) as avg_latency,
                       COALESCE(MIN(latency_ms), 0) as min_latency,
                       COALESCE(MAX(latency_ms), 0) as max_latency
                FROM checks {since_clause}
            """, params).fetchone()
            stats['checks'] = dict(row) if row else {'total': 0, 'up_count': 0, 'avg_latency': 0, 'min_latency': 0, 'max_latency': 0}
            
            # Speed stats
            row = conn.execute(f"""
                SELECT COUNT(*) as total, 
                       COALESCE(AVG(download_mbps), 0) as avg_down,
                       COALESCE(MAX(download_mbps), 0) as max_down,
                       COALESCE(AVG(upload_mbps), 0) as avg_up, 
                       COALESCE(MAX(upload_mbps), 0) as max_up
                FROM speed_tests {since_clause}
            """, params).fetchone()
            stats['speed'] = dict(row) if row else {'total': 0, 'avg_down': 0, 'max_down': 0, 'avg_up': 0, 'max_up': 0}
            
            # Device stats
            row = conn.execute(f"""
                SELECT COUNT(DISTINCT ip) as unique_devices
                FROM devices {since_clause}
            """, params).fetchone()
            stats['devices'] = dict(row) if row else {}
            
            # Event stats
            row = conn.execute(f"""
                SELECT event_type, COUNT(*) as count
                FROM events {since_clause}
                GROUP BY event_type
            """, params).fetchall()
            stats['events'] = {r[0]: r[1] for r in row}
            
            return stats

    def export(self, format: str = 'json', since: Optional[float] = None,
               until: Optional[float] = None) -> str:
        """Export data in specified format."""
        import io
        data = {
            'checks': [asdict(c) for c in self.get_checks(since, until, 10000)],
            'speed_tests': [asdict(s) for s in self.get_speed_tests(since, until, 10000)],
            'devices': [asdict(d) for d in self.get_devices(since, until, 10000)],
            'events': [asdict(e) for e in self.get_events(since, until, 10000)],
        }
        
        if format == 'json':
            return json.dumps(data, indent=2)
        elif format == 'csv':
            # Export each table as separate CSV
            import io
            output = io.StringIO()
            for table, records in data.items():
                if records:
                    output.write(f"# {table}\n")
                    writer = csv.DictWriter(output, fieldnames=records[0].keys())
                    writer.writeheader()
                    for r in records:
                        writer.writerow(r)
                    output.write('\n')
            return output.getvalue()
        else:
            raise ValueError(f"Unsupported format: {format}")

    def cleanup_old(self, days: int = 30):
        """Remove records older than specified days."""
        cutoff = time.time() - (days * 86400)
        with self._lock:
            with self._get_conn() as conn:
                for table in ['checks', 'speed_tests', 'devices', 'events']:
                    conn.execute(f"DELETE FROM {table} WHERE timestamp < ?", (cutoff,))
                conn.commit()
            # VACUUM must be run outside transaction
            with self._get_conn() as conn:
                conn.execute("VACUUM")

    def rotate_daily(self):
        """Rotate database daily (keep current + archive)."""
        # Archive current DB with date suffix
        date_str = datetime.now().strftime('%Y%m%d')
        archive_path = self.data_dir / f'history_{date_str}.db'
        
        if self.db_path.exists():
            shutil.copy2(self.db_path, archive_path)
            # Compress archive
            with open(archive_path, 'rb') as f_in:
                with gzip.open(f"{archive_path}.gz", 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            archive_path.unlink()
        
        # Reset current DB
        self._init_db()

    def close(self):
        """Shutdown writer thread."""
        self._stop_writer.set()
        if self._writer_thread:
            self._writer_thread.join(timeout=5.0)


# Global instance
_history_manager: Optional[HistoryManager] = None


def get_history_manager() -> HistoryManager:
    """Get global history manager instance."""
    global _history_manager
    if _history_manager is None:
        _history_manager = HistoryManager()
    return _history_manager