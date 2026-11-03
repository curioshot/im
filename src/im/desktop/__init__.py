"""Desktop GUI for im - Internet Monitor.

This module provides a simple cross-platform desktop GUI using tkinter,
which is pre-installed on most Python installations.
"""

import sys
import os
import threading
import time
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:
    print("Error: tkinter is not installed. Please install python3-tk package.")
    sys.exit(1)

from im.core.monitor import Monitor, SpeedTester, DeviceMonitor, Traffic
from im.platform import get_platform
from im.core.config import config
from im.core.render import fmt_duration, fmt_speed, fmt_mb, fmt_ms
from rich.console import Console


def launch_desktop(background: bool = False, settings: bool = False, dev: bool = False):
    """Launch the desktop application.

    Args:
        background: Start minimized to system tray (not implemented yet)
        settings: Open settings dialog directly (not implemented yet)
        dev: Run in development mode (not implemented yet)
    """
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        print("Error: tkinter is not installed. Please install python3-tk package.")
        sys.exit(1)

    root = tk.Tk()
    root.title("im - Internet Monitor")
    root.geometry("900x700")
    root.minsize(700, 500)

    # Create the desktop app
    app = DesktopApp(root)

    # Start monitoring in background thread
    monitor_thread = threading.Thread(target=_run_monitor, args=(app,), daemon=True)
    monitor_thread.start()

    root.mainloop()


class DesktopApp:
    """Main desktop application window."""

    def __init__(self, root):
        self.root = root
        self.root.title("im - Internet Monitor")

        # State
        self.status = "Starting..."
        self.latency = None
        self.download = None
        self.upload = None
        self.packet_loss = 0.0
        self.devices = []
        self.checks = 0
        self.failed = 0

        # Build UI
        self._build_ui()

        # Start update loop
        self._update_loop()

    def _build_ui(self):
        """Build the UI layout."""
        # Header
        header_frame = tk.Frame(self.root, bg="#2c3e50", height=60)
        header_frame.pack(fill=tk.X, padx=0, pady=0)
        header_frame.pack_propagate(False)

        title_label = tk.Label(
            header_frame,
            text="im - Internet Monitor",
            font=("Segoe UI", 18, "bold"),
            bg="#2c3e50",
            fg="#ecf0f1",
        )
        title_label.pack(side=tk.LEFT, padx=20, pady=15)

        # Status indicator
        self.status_label = tk.Label(
            header_frame,
            text="Starting...",
            font=("Segoe UI", 10),
            bg="#2c3e50",
            fg="#f1c40f",
        )
        self.status_label.pack(side=tk.RIGHT, padx=20, pady=15)

        # Main content area with scrollbar
        main_frame = tk.Frame(self.root, bg="#ecf0f1")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Create scrollable canvas
        canvas = tk.Canvas(main_frame, bg="#ecf0f1", highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        self.scrollable_frame = tk.Frame(canvas, bg="#ecf0f1")

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )

        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Status cards row
        stats_frame = tk.Frame(self.scrollable_frame, bg="#ecf0f1")
        stats_frame.pack(fill=tk.X, pady=10)

        self.status_card = self._create_stat_card(stats_frame, "Status", "Starting...", "blue")
        self.latency_card = self._create_stat_card(stats_frame, "Latency", "N/A", "blue")
        self.download_card = self._create_stat_card(stats_frame, "Download", "N/A", "green")
        self.upload_card = self._create_stat_card(stats_frame, "Upload", "N/A", "orange")

        # Timeline chart section
        timeline_frame = tk.Frame(self.scrollable_frame, bg="#ecf0f1")
        timeline_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        timeline_label = tk.Label(
            timeline_frame, text="Latency Timeline", font=("Segoe UI", 14, "bold"), bg="#ecf0f1", fg="#2c3e50"
        )
        timeline_label.pack(anchor="w", pady=5)

        self.timeline_canvas = tk.Canvas(timeline_frame, bg="#ffffff", height=200, highlightthickness=1)
        self.timeline_canvas.pack(fill=tk.BOTH, expand=True)

        # Device list section
        devices_frame = tk.Frame(self.scrollable_frame, bg="#ecf0f1")
        devices_frame.pack(fill=tk.X, pady=10)

        devices_label = tk.Label(
            devices_frame, text="Connected Devices", font=("Segoe UI", 14, "bold"), bg="#ecf0f1", fg="#2c3e50"
        )
        devices_label.pack(anchor="w", pady=5)

        self.devices_tree = ttk.Treeview(
            devices_frame,
            columns=("ip", "mac", "state", "first_seen"),
            show="headings",
            height=6,
        )
        self.devices_tree.heading("ip", text="IP Address")
        self.devices_tree.heading("mac", text="MAC Address")
        self.devices_tree.heading("state", text="State")
        self.devices_tree.heading("first_seen", text="First Seen")
        self.devices_tree.column("ip", width=150)
        self.devices_tree.column("mac", width=150)
        self.devices_tree.column("state", width=100)
        self.devices_tree.column("first_seen", width=120)
        self.devices_tree.pack(fill=tk.X, pady=5)

        # Recent checks table
        checks_frame = tk.Frame(self.scrollable_frame, bg="#ecf0f1")
        checks_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        checks_label = tk.Label(
            checks_frame, text="Recent Checks", font=("Segoe UI", 14, "bold"), bg="#ecf0f1", fg="#2c3e50"
        )
        checks_label.pack(anchor="w", pady=5)

        self.checks_tree = ttk.Treeview(
            checks_frame,
            columns=("time", "status", "latency"),
            show="headings",
            height=8,
        )
        self.checks_tree.heading("time", text="Time")
        self.checks_tree.heading("status", text="Status")
        self.checks_tree.heading("latency", text="Latency")
        self.checks_tree.column("time", width=150)
        self.checks_tree.column("status", width=100)
        self.checks_tree.column("latency", width=100)
        self.checks_tree.pack(fill=tk.BOTH, expand=True)

    def _create_stat_card(self, parent, label, value, color):
        """Create a stat card widget."""
        card = tk.Frame(parent, bg="#ffffff", relief=tk.RAISED, bd=1)
        card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        label_label = tk.Label(card, text=label, font=("Segoe UI", 10), bg="#ffffff", fg="#7f8c8d")
        label_label.pack(pady=(10, 0))

        value_label = tk.Label(
            card, text=value, font=("Segoe UI", 24, "bold"), bg="#ffffff", fg=color
        )
        value_label.pack(pady=(0, 10))

        # Store reference for updates
        card.value_label = value_label
        return card

    def _update_loop(self):
        """Update the UI with latest data."""
        # Update status cards
        self.status_label.config(
            text=f"{self.status}",
            fg="#2ecc71" if self.status == "Online" else "#e74c3c",
        )
        self.status_card.value_label.config(text=self.status)
        self.latency_card.value_label.config(text=self.latency if self.latency else "N/A")
        self.download_card.value_label.config(
            text=f"{self.download:.1f} Mbps" if self.download else "N/A"
        )
        self.upload_card.value_label.config(
            text=f"{self.upload:.1f} Mbps" if self.upload else "N/A"
        )

        # Update timeline
        self._update_timeline()

        # Update devices
        self._update_devices()

        # Schedule next update
        self.root.after(1000, self._update_loop)

    def _update_timeline(self):
        """Update the latency timeline canvas."""
        self.timeline_canvas.delete("all")
        width = self.timeline_canvas.winfo_width()
        height = self.timeline_canvas.winfo_height()

        if width < 10 or height < 10:
            return

        # Draw axis lines
        self.timeline_canvas.create_line(40, 10, 40, height - 30, fill="#bdc3c7", width=1)
        self.timeline_canvas.create_line(40, height - 30, width - 10, height - 30, fill="#bdc3c7", width=1)

        # Draw latency history
        samples = self.checks_list[-30:]  # Last 30 samples
        if len(samples) < 2:
            return

        max_latency = max((lat for up, lat in samples if lat is not None), default=0)
        if max_latency == 0:
            max_latency = 100

        x_step = (width - 50) / (len(samples) - 1) if len(samples) > 1 else 0

        points = []
        for i, (up, lat) in enumerate(samples):
            x = 40 + i * x_step
            if lat is not None:
                y = height - 30 - lat / max_latency * (height - 40)
            else:
                y = height - 30  # Bottom for down/failed probes
            points.append((x, y))

        # Draw line
        for i in range(len(points) - 1):
            self.timeline_canvas.create_line(
                points[i][0], points[i][1], points[i + 1][0], points[i + 1][1],
                fill="#3498db", width=2
            )

        # Draw points
        for x, y in points:
            self.timeline_canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill="#3498db", outline="#2980b9", width=1)

    def _update_devices(self):
        """Update the devices table."""
        # Clear existing items
        for item in self.devices_tree.get_children():
            self.devices_tree.delete(item)

        for device in self.devices:
            self.devices_tree.insert(
                "", "end",
                values=(device.get("ip", "-"), device.get("mac", "-"), device.get("state", "-"), device.get("first", "-"))
            )

    def update_data(self, data):
        """Update internal state from monitor data."""
        self.status = "Online" if data.get("up") else "Offline"
        self.latency = data.get("avg_lat")
        # download/upload are set separately from speed test data via update_speed()
        # devices are set separately from devices monitor via update_devices()
        self.checks_list = data.get("timeline", [])
        self.failed = data.get("failed", 0)


def _run_monitor(app):
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

    while mon.running:
        try:
            snap = mon.snapshot()
            spd = speed.snapshot()
            dev = devices.snapshot()
            traffic_snap = traffic.snapshot()

            # Update app data
            app.up = snap.get("up", False)
            app.latency = snap.get("avg_lat")
            app.download = spd.get("down")
            app.upload = spd.get("up")
            app.packet_loss = 0.0
            if snap.get("total", 0) > 0:
                app.packet_loss = (snap.get("failed", 0) / snap["total"]) * 100
            app.checks = snap.get("total", 0)
            app.failed = snap.get("failed", 0)
            app.devices = dev.get("entries", [])

            app.update_data(snap)

            time.sleep(1.0)
        except Exception as e:
            print(f"Monitor error: {e}")
            time.sleep(1.0)

    mon.running = False
    speed.stop()
    devices.stop()
    traffic.stop()