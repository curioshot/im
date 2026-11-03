#!/usr/bin/env python3
"""
im - Internet Monitor
Cross-platform desktop GUI application using Tkinter.
Designed with Stitch design system - Dark mode, INTER font, ROUND_EIGHT radius.
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


# ══════════════════════════════════════════════════════════════════════════════
# STITCH DESIGN SYSTEM - DESIGN TOKENS
# ══════════════════════════════════════════════════════════════════════════════

# Color Palette (Dark Mode - im-dark-theme)
COLORS = {
    # Background Canvas
    "bg": "#1a1a2e",           # Primary canvas background
    "surface": "#16213e",      # Card backgrounds
    "surface_bright": "#0c0c1f", # Active/selected states
    "surface_container": "#1a1a2e", # Lower surface containers
    "surface_container_high": "#28283d", # Higher elevation surfaces

    # Text Colors
    "text_primary": "#e2e0fc",   # Core legible text
    "text_secondary": "#c0c7d1", # Secondary labels
    "text_muted": "#7f8c8d",     # Muted accents

    # Accent Colors
    "accent_primary": "#64b5f6", # Primary actions, links
    "accent_success": "#4caf50", # Online, good status
    "accent_warning": "#ff9800", # Degraded, warnings
    "accent_error": "#f44336",   # Offline, errors

    # Structural
    "border": "#37474f",       # Borders, dividers
    "focus_ring": "#64b5f6",   # Focus ring
}

# Typography (Inter font)
FONTS = {
    "display": ("Inter", 28, "bold"),
    "headline_lg": ("Inter", 20, "bold"),
    "headline_md": ("Inter", 16, "bold"),
    "headline_sm": ("Inter", 16, "bold"),
    "body_lg": ("Inter", 15, "normal"),
    "body_md": ("Inter", 14, "normal"),
    "body_sm": ("Inter", 12, "normal"),
    "label_lg": ("Inter", 12, "bold"),
    "label_md": ("Inter", 11, "bold"),
    "label_sm": ("Inter", 11, "bold"),
    "code": ("JetBrains Mono", 12, "normal"),
    "metric": ("Inter", 28, "bold"),
}

# Spacing
SPACING = {
    "xs": 4,   # 0.25rem
    "sm": 8,   # 0.5rem
    "md": 16,  # 1rem
    "lg": 24,  # 1.5rem
    "xl": 32,  # 2rem
}

# Border Radius
BORDER_RADIUS = {
    "sm": 4,
    "md": 8,   # Default - ROUND_EIGHT
    "lg": 16,
    "xl": 24,
    "full": 9999,
}


class DesktopApp:
    """Main desktop application window for Internet Monitor."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("im - Internet Monitor")
        self.root.geometry("900x700")
        self.root.minsize(700, 500)
        self.root.configure(bg=COLORS["bg"])

        # State
        self.status = "Starting..."
        self.latency = None
        self.download = None
        self.upload = None
        self.packet_loss = 0.0
        self.devices = []
        self.checks_list = []  # List of (up, lat) tuples
        self.failed = 0

        # Build UI
        self._build_ui()

        # Start update loop
        self._update_loop()

    def _build_ui(self):
        """Build the UI layout."""
        # Header
        header_frame = tk.Frame(self.root, bg=COLORS["bg"], height=60)
        header_frame.pack(fill=tk.X, padx=0, pady=0)
        header_frame.pack_propagate(False)

        title_label = tk.Label(
            header_frame,
            text="🌐  im - Internet Monitor",
            font=FONTS["headline_lg"],
            bg=COLORS["bg"],
            fg=COLORS["text_primary"],
        )
        title_label.pack(side=tk.LEFT, padx=20, pady=15)

        # Status indicator
        self.status_label = tk.Label(
            header_frame,
            text="Starting...",
            font=FONTS["body_md"],
            bg=COLORS["bg"],
            fg=COLORS["text_secondary"],
        )
        self.status_label.pack(side=tk.RIGHT, padx=20, pady=15)

        # Main content area with scrollbar
        main_frame = tk.Frame(self.root, bg=COLORS["bg"])
        main_frame.pack(fill=tk.BOTH, expand=True, padx=SPACING["sm"], pady=SPACING["sm"])

        # Create scrollable canvas
        canvas = tk.Canvas(main_frame, bg=COLORS["bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        self.scrollable_frame = tk.Frame(canvas, bg=COLORS["bg"])

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )

        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Status cards row
        stats_frame = tk.Frame(self.scrollable_frame, bg=COLORS["bg"])
        stats_frame.pack(fill=tk.X, pady=SPACING["sm"])

        self.status_card = self._create_stat_card(stats_frame, "Status", "Starting...", COLORS["accent_primary"])
        self.latency_card = self._create_stat_card(stats_frame, "Latency", "N/A", COLORS["accent_success"])
        self.download_card = self._create_stat_card(stats_frame, "Download", "N/A", COLORS["accent_success"])
        self.upload_card = self._create_stat_card(stats_frame, "Upload", "N/A", "#a9c8fc")

        # Timeline section
        timeline_frame = tk.Frame(self.scrollable_frame, bg=COLORS["bg"])
        timeline_frame.pack(fill=tk.BOTH, expand=True, pady=SPACING["sm"])

        timeline_label = tk.Label(
            timeline_frame,
            text="Latency Timeline",
            font=FONTS["label_lg"],
            bg=COLORS["bg"],
            fg=COLORS["text_secondary"],
        )
        timeline_label.pack(anchor="w", pady=SPACING["xs"])

        self.timeline_canvas = tk.Canvas(timeline_frame, bg=COLORS["surface_container"], height=200, highlightthickness=1, highlightbackground=COLORS["border"])
        self.timeline_canvas.pack(fill=tk.BOTH, expand=True)

        # Device list section
        devices_frame = tk.Frame(self.scrollable_frame, bg=COLORS["bg"])
        devices_frame.pack(fill=tk.X, pady=SPACING["sm"])

        devices_label = tk.Label(
            devices_frame,
            text="Connected Devices",
            font=FONTS["label_lg"],
            bg=COLORS["bg"],
            fg=COLORS["text_secondary"],
        )
        devices_label.pack(anchor="w", pady=SPACING["xs"])

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
        self.devices_tree.pack(fill=tk.X, pady=SPACING["sm"])

        # Recent checks table
        checks_frame = tk.Frame(self.scrollable_frame, bg=COLORS["bg"])
        checks_frame.pack(fill=tk.BOTH, expand=True, pady=SPACING["sm"])

        checks_label = tk.Label(
            checks_frame,
            text="Recent Checks",
            font=FONTS["label_lg"],
            bg=COLORS["bg"],
            fg=COLORS["text_secondary"],
        )
        checks_label.pack(anchor="w", pady=SPACING["xs"])

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
        card = tk.Frame(parent, bg=COLORS["surface"], relief="flat", bd=1)
        card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=SPACING["sm"], pady=SPACING["xs"])

        label_label = tk.Label(card, text=label, font=FONTS["label_sm"], bg=COLORS["surface"], fg=COLORS["text_secondary"])
        label_label.pack(pady=(SPACING["sm"], SPACING["xs"]))

        value_label = tk.Label(card, text=value, font=FONTS["metric"], bg=COLORS["surface"], fg=color)
        value_label.pack(pady=(SPACING["xs"], SPACING["sm"]))

        # Store reference for updates
        card.value_label = value_label
        return card

    def _update_loop(self):
        """Update the UI with latest data."""
        # Update status cards
        self.status_label.config(text=self.status, fg=self._status_color())
        self.status_card.value_label.config(text=self.status)
        self.latency_card.value_label.config(text=f"{self.latency} ms" if self.latency else "N/A")
        self.download_card.value_label.config(text=f"{self.download:.1f} Mbps" if self.download is not None else "N/A")
        self.upload_card.value_label.config(text=f"{self.upload:.1f} Mbps" if self.upload else "N/A")

        # Update timeline
        self._update_timeline()

        # Update devices
        self._update_devices()

        # Schedule next update
        self.root.after(1000, self._update_loop)

    def _status_color(self):
        """Return color based on connection status."""
        return COLORS["accent_success"] if self.status == "Online" else COLORS["accent_error"]

    def _update_timeline(self):
        """Update the latency timeline canvas."""
        self.timeline_canvas.delete("all")
        width = self.timeline_canvas.winfo_width()
        height = self.timeline_canvas.winfo_height()

        if width < 10 or height < 10:
            return

        # Draw axis lines
        self.timeline_canvas.create_line(40, 10, 40, height - 30, fill=COLORS["border"], width=1)
        self.timeline_canvas.create_line(40, height - 30, width - 10, height - 30, fill=COLORS["border"], width=1)

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
                fill=COLORS["accent_primary"], width=2
            )

        # Draw points
        for x, y in points:
            self.timeline_canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=COLORS["accent_primary"], outline=COLORS["border"], width=1)

    def _update_devices(self):
        """Update the devices table."""
        # Clear existing items
        for item in self.devices_tree.get_children():
            self.devices_tree.delete(item)

        for entry in self.devices:
            self.devices_tree.insert(
                "", "end",
                values=(entry.get("ip", "-"), entry.get("mac", "-"), entry.get("state", "-"), entry.get("first", "-"))
            )

    def update_data(self, snap):
        """Update internal state from monitor data."""
        self.status = "Online" if snap.get("up") else "Offline"
        self.latency = data.get("avg_lat")
        self.checks_list = data.get("timeline", [])
        self.failed = data.get("failed", 0)
        self.devices = data.get("devices", [])

    def update_speed(self, down_mbps, up_mbps):
        """Update speed test data."""
        self.download = down_mbps
        self.upload = up_mbps

    def update_devices(self, dev_entries):
        """Update device list."""
        self.devices = dev_entries


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
            app.checks_list = snap.get("timeline", [])
            app.failed = snap.get("failed", 0)
            app.devices = dev.get("entries", [])

            app.update_data(snap)

            time.sleep(1.0)
        except Exception as exc:
            print(f"Monitor error: {exc}")
            time.sleep(1.0)

    mon.running = False
    speed.stop()
    devices.stop()
    traffic.stop()


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