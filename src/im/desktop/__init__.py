#!/usr/bin/env python3
"""
im - Internet Monitor Desktop Application
Cross-platform desktop GUI with HTML/CSS/JS frontend.
Designed with Stitch design system - Dark mode, INTER font, ROUND_EIGHT radius.
"""

import sys
import os
import threading
import time
import subprocess
import webbrowser
from pathlib import Path

from im.core.monitor import Monitor, SpeedTester, DeviceMonitor, Traffic
from im.platform import get_platform
from im.core.config import config
from im.core.render import fmt_duration, fmt_speed, fmt_mb, fmt_ms


def launch_desktop(background: bool = False, settings: bool = False, dev: bool = False):
    """Launch the desktop application.

    Args:
        background: Start minimized to system tray (not implemented yet)
        settings: Open settings dialog directly (not implemented yet)
        dev: Run in development mode (not implemented yet)
    """
    # Find the desktop app directory
    desktop_dir = Path(__file__).parent.parent / "im-desktop"
    html_file = desktop_dir / "index.html"

    if not html_file.exists():
        print("Error: Desktop app HTML not found at", desktop_dir / "index.html")
        sys.exit(1)

    # Start the monitor backend in a thread
    mon_thread = threading.Thread(target=_run_monitor, args=(desktop_dir,), daemon=True)
    mon_thread.start()

    # Launch the HTML desktop app using the default browser or electron if available
    html_path = str(desktop_dir / "index.html").replace(" ", "%20")
    file_url = f"file://{html_file}"

    # Try to open in default browser first
    import webbrowser
    webbrowser.open(file_url, new=1)

    # Keep the process alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


def _run_monitor(desktop_dir: Path):
    """Run the monitor in a background thread."""
    import time

    from im.core import Monitor, SpeedTester, DeviceMonitor, Traffic

    mon = Monitor(1.0, 1.5)
    mon.start()

    speed = SpeedTester(enabled=True, interval=1.0, gate=lambda: mon.up is not False)
    speed.start()

    devices = DeviceMonitor(enable_dns=False)
    devices.start()

    traffic = Traffic()
    traffic.start()

    # Store data for the desktop app to read
    data_dir = desktop_dir / "data"
    data_dir.mkdir(exist_ok=True)
    state_file = data_dir / "monitor_state.json"

    while mon.running:
        try:
            snap = mon.snapshot()
            spd = speed.snapshot()
            dev = devices.snapshot()
            traffic_snap = traffic.snapshot()

            data = {
                "status": "Online" if snap.get("up") else "Offline",
                "latency": snap.get("avg_lat"),
                "download": spd.get("down"),
                "upload": spd.get("up"),
                "failed": snap.get("failed", 0),
                "total": snap.get("total", 0),
                "devices": dev.get("entries", []),
                "timeline": snap.get("timeline", []),
            }

            # Write state to file for the desktop app to read
            with open(data_dir / "state.json", "w") as f:
                import json
                json.dump(data, f)

            time.sleep(1.0)
        except Exception as exc:
            print(f"Monitor error: {exc}")
            time.sleep(1.0)

    mon.running = False
    speed.stop()
    devices.stop()
    traffic.stop()