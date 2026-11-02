"""Run command - main monitor entry point."""

import sys
import select
import os
import time
from typing import Optional

import typer
from rich.console import Console
from rich.live import Live

from im.core import Monitor, SpeedTester, DeviceMonitor, Traffic, render
from im.core.config import config


app = typer.Typer(name="run", help="Start the internet monitor")


@app.callback(invoke_without_command=True)
def run(
    ctx: typer.Context,
    interval: float = typer.Option(1.0, "-i", "--interval", help="Check interval in seconds"),
    timeout: float = typer.Option(1.5, "-t", "--timeout", help="Probe timeout in seconds"),
    duration: int = typer.Option(0, "--duration", help="Stop after N seconds (0 = forever)"),
    no_speed: bool = typer.Option(False, "--no-speed", help="Disable speed test"),
    root: bool = typer.Option(False, "--root", help="Enable DNS browsing log (needs root/admin)"),
    no_install: bool = typer.Option(False, "--no-install", help="Skip auto-install, fail if deps missing"),
):
    """Start the internet monitor TUI."""
    console = Console()

    # Merge with config defaults
    interval = config.get("interval", interval)
    timeout = config.get("timeout", timeout)
    duration = config.get("duration", duration)
    no_speed = config.get("no_speed", no_speed)
    root = config.get("root", root)

    # Initialize components
    mon = Monitor(max(interval, 0.1), timeout)
    mon.start()

    speed = SpeedTester(
        enabled=not no_speed,
        interval=mon.interval,
        gate=lambda: mon.up is not False,
    )
    speed.start()

    devices = DeviceMonitor(enable_dns=root)
    devices.start()

    traffic = Traffic()
    traffic.start()

    # Set up raw keyboard input
    from im.platform import get_platform
    platform = get_platform()
    restore_keyboard = platform.setup_raw_keyboard()

    started = time.monotonic()
    try:
        with Live(render(mon, console, speed, devices, traffic), console=console, screen=True, refresh_per_second=10) as live:
            while True:
                if duration and time.monotonic() - started >= duration:
                    break
                live.update(render(mon, console, speed, devices, traffic))

                # Check for keyboard input
                if sys.stdin.isatty():
                    ready, _, _ = select.select([sys.stdin], [], [], 0.1)
                    if ready:
                        key = os.read(sys.stdin.fileno(), 1).decode(errors="ignore").lower()
                        if key == "q":
                            break
                        if key == "r":
                            mon.reset()
                        if key in ("+", "="):
                            new_interval = mon.change_interval(2.0)
                            speed.interval = max(new_interval, 0.5)
                        if key in ("-", "_"):
                            new_interval = mon.change_interval(0.5)
                            speed.interval = max(new_interval, 0.5)
                else:
                    time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        mon.running = False
        speed.stop()
        devices.stop()
        traffic.stop()
        restore_keyboard()

    # Print session summary
    snap = mon.snapshot()
    spd = speed.snapshot()
    ok = snap["total"] - snap["failed"]
    console.print(
        f"[bold]Session ended[/] · {snap['total']} checks · {ok} online · "
        f"{fmt_duration(time.monotonic() - snap['started'])}"
    )
    if spd["enabled"]:
        parts = []
        downs = spd["down_hist"]
        ups = spd["up_hist"]
        if downs:
            avg = sum(downs) / len(downs)
            peak = max(downs)
            parts.append(
                f"↓ avg {fmt_speed(avg)} ({fmt_mb(avg)}) "
                f"peak {fmt_speed(peak)} ({fmt_mb(peak)})"
            )
        if ups:
            avg = sum(ups) / len(ups)
            peak = max(ups)
            parts.append(
                f"↑ avg {fmt_speed(avg)} ({fmt_mb(avg)}) "
                f"peak {fmt_speed(peak)} ({fmt_mb(peak)})"
            )
        if spd["errors"] or spd["up_errors"]:
            parts.append(f"{spd['errors']} down / {spd['up_errors']} up errors")
        console.print("[bold]Speed[/] · " + (" · ".join(parts) or "no samples"))
    dev = devices.snapshot()
    extra = ""
    if dev["dns_on"]:
        extra = f" · {len(dev['dns_log'])} dns queries logged"
    console.print(
        f"[bold]Devices[/] · {len(dev['entries'])} seen on LAN"
        + (f" · {sum(1 for e in dev['entries'] if e['state'] in ('REACHABLE', 'DELAY', 'PROBE'))} active" if dev['entries'] else "")
        + extra
    )


# Import formatting functions
from im.core.render import fmt_duration, fmt_speed, fmt_mb


if __name__ == "__main__":
    app()