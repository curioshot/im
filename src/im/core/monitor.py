"""Core monitoring logic - extracted from netmon.py."""

import argparse
import http.client
import json
import os
import re
import select
import socket
import shutil
import ssl
import subprocess
import sys
import termios
import threading
import time
import tty
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any
from urllib.request import Request, urlopen

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

# Import platform abstraction
from im.platform import get_platform
from im.core.history import get_history_manager


# Constants from original netmon.py
FAST_PROBES = [
    ("Cloudflare", "1.1.1.1", 443),
    ("Google DNS", "8.8.8.8", 53),
]
DEEP_PROBES = [
    ("Quad9", "9.9.9.9", 443),
]
HTTP_URL = "http://connectivitycheck.gstatic.com/generate_204"
SPEED_HOST = "speed.cloudflare.com"
SPEED_STREAM = 64 * 1024 * 1024
READ_SIZE = 64 * 1024
READ_TIMEOUT = 0.5
STALL_TIMEOUT = 10.0
SETUP_TIMEOUT = 10.0
UPLOAD_SIZE = 256 * 1024
BLOCKS = " ▁▂▃▄▅▆▇█"
NEIGH_LIVE = ("REACHABLE", "DELAY", "PROBE")
DEV_SCAN_INTERVAL = 10.0
DEVICE_ROWS = 6


def tcp_probe(host, port, timeout):
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, (time.perf_counter() - start) * 1000.0, ""
    except OSError as exc:
        return False, None, type(exc).__name__


def http_probe(timeout):
    start = time.perf_counter()
    try:
        req = Request(HTTP_URL, method="GET", headers={"User-Agent": "netmon"})
        with urlopen(req, timeout=timeout) as resp:
            resp.read(1)
            ok = resp.status in (200, 204)
            code = resp.status
        return ok, (time.perf_counter() - start) * 1000.0, "" if ok else f"HTTP {code}"
    except Exception as exc:
        return False, None, type(exc).__name__


def run_probes(probes, timeout):
    with ThreadPoolExecutor(max_workers=max(len(probes), 1)) as pool:
        futures = {
            name: pool.submit(tcp_probe, host, port, timeout)
            for name, host, port in probes
        }
        return {name: future.result() for name, future in futures.items()}


def local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("1.1.1.1", 80))
            return sock.getsockname()[0]
    except OSError:
        return "-"


def fmt_bytes(value):
    if value is None:
        return "-"
    value = max(float(value), 0.0)
    unit = "B"
    for up in ("KB", "MB", "GB", "TB"):
        if value < 1024:
            break
        value /= 1024.0
        unit = up
    return f"{value:,.1f} {unit}" if value >= 100 else f"{value:.2f} {unit}"


def valid_mac(mac):
    if not mac:
        return False
    parts = mac.split(":")
    if len(parts) != 6:
        return False
    uniq = {p.lower() for p in parts}
    return uniq not in ({"00"}, {"ff"})


def fmt_duration(seconds):
    seconds = int(max(seconds, 0))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def fmt_ms(value):
    if value is None:
        return "-"
    return f"{value:.0f} ms" if value < 1000 else f"{value / 1000:.1f} s"


def fmt_speed(mbps):
    if mbps is None:
        return "-"
    return f"{mbps * 1000:.0f} kbps" if mbps < 1 else f"{mbps:.1f} Mbps"


def fmt_mb(mbps):
    if mbps is None:
        return "-"
    value = mbps / 8.0
    if 0 < value < 0.01:
        return "<0.01 MB/s"
    return f"{value:.2f} MB/s" if value < 10 else f"{value:.1f} MB/s"


def speed_glyph(mbps, scale):
    frac = min(max(mbps / scale, 0.0), 1.0) ** 0.5
    return BLOCKS[1 + int(frac * (len(BLOCKS) - 2))]


def latency_glyph(latency, scale):
    frac = min(max((latency or 0) / scale, 0.0), 1.0)
    return BLOCKS[1 + int(frac * (len(BLOCKS) - 2))]


class Monitor:
    """Main connectivity monitor."""

    def __init__(self, interval, timeout):
        self.interval = interval
        self.timeout = timeout
        self.fast_timeout = min(timeout, max(interval, 0.5))
        self.lock = threading.Lock()
        self.started = time.monotonic()
        self.running = True
        self.timeline = deque(maxlen=600)
        self.latencies = deque(maxlen=600)
        self.fast_results = {}
        self.deep_results = {}
        self.events = []
        self.up = None
        self.changed_at = self.started
        self.total = 0
        self.failed = 0
        self.total_lat = 0.0
        self.lat_count = 0
        self.min_lat = None
        self.max_lat = None
        self.local_ip = local_ip()
        self.gateway = "-"
        self.wifi = "-"
        self.inflight = 0
        self.deep_busy = False

        # Get platform-specific gateway
        platform = get_platform()
        self.gateway = platform.get_default_gateway()
        self.wifi = platform.get_wifi_info()

    def start(self):
        threading.Thread(target=self._scheduler, daemon=True).start()

    def _scheduler(self):
        next_at = time.monotonic()
        tick = 0
        while self.running:
            now = time.monotonic()
            if now < next_at:
                time.sleep(min(next_at - now, 0.05))
                continue
            with self.lock:
                busy = self.inflight >= 3
                if not busy:
                    self.inflight += 1
            if not busy:
                threading.Thread(target=self._tick, args=(tick,), daemon=True).start()
                tick += 1
            next_at += self.interval
            if next_at < time.monotonic():
                next_at = time.monotonic()

    def _tick(self, tick):
        try:
            results = run_probes(FAST_PROBES, self.fast_timeout)
            lat = min((ms for ok, ms, _ in results.values() if ok and ms is not None), default=None)
            now = time.monotonic()
            with self.lock:
                previous = self.up
                self.up = any(ok for ok, _, _ in results.values())
                self.fast_results = results
                self.total += 1
                self.timeline.append((self.up, lat))
                if lat is not None:
                    self.latencies.append(lat)
                    self.total_lat += lat
                    self.lat_count += 1
                    self.min_lat = lat if self.min_lat is None else min(self.min_lat, lat)
                    self.max_lat = lat if self.max_lat is None else max(self.max_lat, lat)
                if not self.up:
                    self.failed += 1
                if previous is not None and previous != self.up:
                    self.changed_at = now
                    stamp = datetime.now().strftime("%H:%M:%S")
                    self.events.append((stamp, "back online" if self.up else "connection lost"))
                    del self.events[:-6]
            # Record to history
            get_history_manager().record_check(self.up, lat, results)
        except Exception as exc:
            with self.lock:
                self.fast_results = {"error": (False, None, type(exc).__name__)}
        finally:
            with self.lock:
                self.inflight -= 1
        if tick % 5 == 0:
            self._deep_async()

    def _deep_async(self):
        with self.lock:
            if self.deep_busy:
                return
            self.deep_busy = True
        threading.Thread(target=self._deep, daemon=True).start()

    def _deep(self):
        platform = get_platform()
        try:
            results = run_probes(DEEP_PROBES, self.timeout)
            results["HTTP 204"] = http_probe(self.timeout)
            wifi = platform.get_wifi_info()
            with self.lock:
                self.deep_results = results
                self.wifi = wifi
                self.local_ip = local_ip()
        finally:
            with self.lock:
                self.deep_busy = False

    def snapshot(self):
        with self.lock:
            results = dict(self.fast_results)
            results.update(self.deep_results)
            return {
                "up": self.up,
                "results": results,
                "timeline": list(self.timeline),
                "latencies": list(self.latencies),
                "events": list(self.events),
                "total": self.total,
                "failed": self.failed,
                "avg_lat": self.total_lat / self.lat_count if self.lat_count else None,
                "min_lat": self.min_lat,
                "max_lat": self.max_lat,
                "local_ip": self.local_ip,
                "gateway": self.gateway,
                "wifi": self.wifi,
                "changed_at": self.changed_at,
                "started": self.started,
            }

    def reset(self):
        with self.lock:
            self.total = self.failed = 0
            self.total_lat = self.lat_count = 0
            self.min_lat = self.max_lat = None
            self.events.clear()

    def change_interval(self, factor):
        with self.lock:
            value = min(max(self.interval * factor, 0.1), 60.0)
            self.interval = value
            self.fast_timeout = min(self.timeout, max(value, 0.5))
        return value


class SpeedTester:
    """Continuous speed test."""

    def __init__(self, enabled, interval, gate=None, upload_every=30.0):
        self.enabled = enabled
        self.interval = max(interval, 0.5)
        self.gate = gate
        self.upload_every = max(upload_every, self.interval)
        self.lock = threading.Lock()
        self.uploading = threading.Event()
        self.running = True
        self.down = None
        self.up = None
        self.down_hist = deque(maxlen=300)
        self.up_hist = deque(maxlen=30)
        self.errors = 0
        self.up_errors = 0
        self.conn = None
        self.up_conn = None
        self.cycles = 0
        self._bytes = 0
        self._last_publish = time.monotonic()

    def start(self):
        if not self.enabled:
            return
        self._last_publish = time.monotonic()
        threading.Thread(target=self._loop, daemon=True).start()
        threading.Thread(target=self._sample_loop, daemon=True).start()
        threading.Thread(target=self._upload_loop, daemon=True).start()

    def stop(self):
        self.running = False
        self._drop()
        self._drop_upload()

    def _connection(self):
        if self.conn is None:
            conn = http.client.HTTPSConnection(
                SPEED_HOST, timeout=SETUP_TIMEOUT,
                context=ssl.create_default_context(),
            )
            try:
                conn.connect()
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
                raise
            self.conn = conn
        return self.conn

    def _upload_connection(self):
        if self.up_conn is None:
            self.up_conn = http.client.HTTPSConnection(
                SPEED_HOST, timeout=20.0, context=ssl.create_default_context()
            )
        return self.up_conn

    def _drop(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
        self.conn = None

    def _drop_upload(self):
        if self.up_conn is not None:
            try:
                self.up_conn.close()
            except Exception:
                pass
        self.up_conn = None

    def _read_stream(self):
        conn = self._connection()
        sock = getattr(conn, "sock", None)
        if sock is not None:
            sock.settimeout(SETUP_TIMEOUT)
        try:
            conn.request(
                "GET", f"/__down?bytes={SPEED_STREAM}",
                headers={"User-Agent": "netmon"},
            )
            resp = conn.getresponse()
        except Exception:
            self._drop()
            raise
        if resp.status != 200:
            self._drop()
            raise RuntimeError(f"HTTP {resp.status}")

        last_data = time.perf_counter()
        while self.running:
            if self.uploading.is_set():
                self._drop()
                return
            if self.gate is not None and not self.gate():
                self._drop()
                return
            sock = getattr(conn, "sock", None)
            if sock is not None:
                sock.settimeout(READ_TIMEOUT)
            try:
                chunk = resp.read1(READ_SIZE)
            except (socket.timeout, TimeoutError):
                chunk = None
            except Exception:
                self._drop()
                raise
            now = time.perf_counter()
            if chunk:
                with self.lock:
                    self._bytes += len(chunk)
                last_data = now
            if now - last_data > STALL_TIMEOUT:
                self._drop()
                raise RuntimeError("stalled")
            if chunk == b"":
                return

    def _upload(self):
        payload = os.urandom(UPLOAD_SIZE)
        conn = self._upload_connection()
        start = time.perf_counter()
        try:
            conn.request(
                "POST", "/__up", body=payload,
                headers={"User-Agent": "netmon", "Content-Type": "application/octet-stream"},
            )
            resp = conn.getresponse()
            resp.read()
        except Exception:
            self._drop_upload()
            raise
        elapsed = time.perf_counter() - start
        if resp.status >= 400:
            self._drop_upload()
            raise RuntimeError(f"HTTP {resp.status}")
        if elapsed <= 0:
            raise RuntimeError("no data")
        return UPLOAD_SIZE * 8 / elapsed / 1e6

    def _loop(self):
        while self.running:
            if self.uploading.is_set():
                time.sleep(0.1)
                continue
            if self.gate is not None and not self.gate():
                time.sleep(self.interval)
                continue
            try:
                self._read_stream()
            except Exception:
                with self.lock:
                    self.errors += 1
                time.sleep(min(self.interval, 1.0))

    def _sample_loop(self):
        next_at = self._last_publish + self.interval
        while self.running:
            now = time.monotonic()
            if now < next_at:
                time.sleep(min(next_at - now, 0.1))
                continue
            with self.lock:
                elapsed = now - self._last_publish
                if self.uploading.is_set():
                    self._bytes = 0
                elif self.gate is not None and not self.gate():
                    self.down = None
                    self._bytes = 0
                elif elapsed > 0:
                    mbps = self._bytes * 8 / elapsed / 1e6
                    self._bytes = 0
                    self.down = mbps
                    self.down_hist.append(mbps)
                    self.cycles += 1
                self._last_publish = now
            next_at += self.interval
            if next_at <= now:
                next_at = now + self.interval

    def _upload_loop(self):
        time.sleep(min(self.upload_every, 10.0))
        while self.running:
            if self.gate is not None and not self.gate():
                with self.lock:
                    self.up = None
                time.sleep(self.interval)
                continue
            self.uploading.set()
            time.sleep(0.15)
            try:
                mbps = self._upload()
                with self.lock:
                    self.up = mbps
                    self.up_hist.append(mbps)
            except Exception:
                with self.lock:
                    self.up_errors += 1
                    self.up = None
            finally:
                self.uploading.clear()
                with self.lock:
                    self._bytes = 0
                    self._last_publish = time.monotonic()
            time.sleep(self.upload_every)

    def snapshot(self):
        with self.lock:
            return {
                "enabled": self.enabled,
                "down": self.down,
                "up": self.up,
                "down_hist": list(self.down_hist),
                "up_hist": list(self.up_hist),
                "cycles": self.cycles,
                "errors": self.errors,
                "up_errors": self.up_errors,
                "uploading": self.uploading.is_set(),
            }


class DeviceMonitor:
    """Monitor LAN devices."""

    def __init__(self, scan_every=DEV_SCAN_INTERVAL, enable_dns=False):
        self.scan_every = scan_every
        self.enable_dns = enable_dns
        self.lock = threading.Lock()
        self.running = True
        self.entries = []
        self.first_seen = {}
        self.hostnames = {}
        self.dns_log = deque(maxlen=60)
        self.dns_note = "browsing log off (run with --root)" if not enable_dns else ""
        self.scan_note = ""
        self.gateway = get_platform().get_default_gateway()

    def start(self):
        threading.Thread(target=self._scan_loop, daemon=True).start()
        if self.enable_dns:
            threading.Thread(target=self._dns_loop, daemon=True).start()

    def stop(self):
        self.running = False

    def _scan_loop(self):
        while self.running:
            self._scan_once()
            time.sleep(self.scan_every)

    def _scan_once(self):
        platform = get_platform()
        arp_entries = platform.get_arp_table()
        scanned = [
            {"ip": e["ip"], "mac": e["mac"].upper(), "state": e["state"]}
            for e in arp_entries
            if valid_mac(e["mac"])
        ]
        now = time.time()
        pending = []
        with self.lock:
            for entry in scanned:
                if entry["ip"] not in self.first_seen:
                    self.first_seen[entry["ip"]] = now
                    pending.append(entry["ip"])
                self.entries = scanned
        if not scanned:
            if shutil.which("ip") is None:
                note = "pkg install iproute2 (or root) to list devices"
            else:
                note = "neighbor table blocked on this system (root/admin needed)"
            with self.lock:
                self.scan_note = note
        for ip in pending:
            name = self._resolve_name(ip)
            if name:
                with self.lock:
                    self.hostnames[ip] = name

    def _resolve_name(self, ip):
        def lookup():
            try:
                return socket.gethostbyaddr(ip)[0]
            except Exception:
                return None
        with ThreadPoolExecutor(max_workers=1) as pool:
            try:
                return pool.submit(lookup).result(timeout=2.0) or None
            except Exception:
                return None

    def _spawn_sniffer(self):
        platform = get_platform()
        sniffer = platform.create_dns_sniffer()
        if sniffer is None:
            with self.lock:
                if not self.dns_note:
                    self.dns_note = "browsing log unavailable (needs root/admin)"
            return None
        return sniffer

    def _dns_loop(self):
        sniffer = self._spawn_sniffer()
        if sniffer is None:
            return
        for src_ip, domain in sniffer:
            stamp = datetime.now().strftime("%H:%M:%S")
            with self.lock:
                self.dns_log.append((stamp, src_ip, domain))
                self.dns_note = ""
        with self.lock:
            if not self.dns_note:
                self.dns_note = "browsing log ended (root/admin needed)"

    def snapshot(self):
        with self.lock:
            entries = sorted(
                self.entries,
                key=lambda e: (e["state"] not in NEIGH_LIVE, e["ip"]),
            )
            queries = Counter(ip for _, ip, _ in self.dns_log)
            for entry in entries:
                stamp = self.first_seen.get(entry["ip"])
                entry["first"] = (
                    datetime.fromtimestamp(stamp).strftime("%H:%M:%S")
                    if stamp else "-"
                )
                entry["queries"] = queries.get(entry["ip"], 0)
            return {
                "entries": entries,
                "hostnames": dict(self.hostnames),
                "dns_log": list(self.dns_log),
                "dns_note": self.dns_note,
                "dns_on": self.enable_dns,
                "scan_note": self.scan_note,
                "gateway": self.gateway,
            }


class Traffic:
    """Per-interface traffic monitor."""

    def __init__(self, poll=1.0, keep=4):
        self.poll = poll
        self.keep = keep
        self.lock = threading.Lock()
        self.running = True
        self.prev = {}
        self.baseline = {}
        self.smoothed = {}
        self._init_counters()

    def _init_counters(self):
        platform = get_platform()
        self.prev = platform.get_interface_counters()
        self.baseline = dict(self.prev)

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self.running = False

    def _loop(self):
        while self.running:
            time.sleep(self.poll)
            platform = get_platform()
            current = platform.get_interface_counters()
            with self.lock:
                for name, counts in current.items():
                    if name in ("lo", "lo0", "Loopback"):
                        continue
                    old = self.prev.get(name)
                    if old is None:
                        continue
                    rx = max(counts[0] - old[0], 0) / self.poll
                    tx = max(counts[1] - old[1], 0) / self.poll
                    last = self.smoothed.get(name)
                    if last is None:
                        self.smoothed[name] = (rx, tx)
                    else:
                        self.smoothed[name] = (
                            rx * 0.6 + last[0] * 0.4,
                            tx * 0.6 + last[1] * 0.4,
                        )
                self.prev = current

    def snapshot(self):
        rows = []
        with self.lock:
            for name, (rx_rate, tx_rate) in list(self.smoothed.items()):
                counts = self.prev.get(name)
                base = self.baseline.get(name)
                if counts is None or base is None:
                    continue
                rows.append({
                    "name": name,
                    "rx_rate": rx_rate,
                    "tx_rate": tx_rate,
                    "rx_session": counts[0] - base[0],
                    "tx_session": counts[1] - base[1],
                })
        rows.sort(key=lambda row: row["rx_rate"] + row["tx_rate"], reverse=True)
        return rows[:self.keep]