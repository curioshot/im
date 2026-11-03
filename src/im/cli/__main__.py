"""Main CLI entry point for im."""

import sys
import time
import typer
from rich.console import Console

from im.cli.commands import install_app, doctor_app, config_app, update_app, history_app, alerts_app
from im.cli.pipeline import PipelineRenderer
from im.installer import get_installer
from im.core.config import config
from im.core.render import fmt_duration, fmt_speed, fmt_mb


app = typer.Typer(
    name="im",
    help="Internet Monitor - Cross-platform connectivity TUI",
    add_completion=False,
    no_args_is_help=False,
    invoke_without_command=False,
)


# Add subcommands
app.add_typer(install_app, name="install")
app.add_typer(doctor_app, name="doctor")
app.add_typer(config_app, name="config")
app.add_typer(update_app, name="update")
app.add_typer(history_app, name="history")
app.add_typer(alerts_app, name="alerts")


@app.command("desktop")
def desktop_cmd(
    background: bool = typer.Option(False, "--background", "-b", help="Start minimized to tray"),
    dev: bool = typer.Option(False, "--dev", help="Run in development mode"),
):
    """Launch the internet monitor desktop application."""
    from im.desktop import launch_desktop
    launch_desktop(background=background, dev=dev)

def _run_monitor_impl(
    interval: float,
    timeout: float,
    duration: int,
    no_speed: bool,
    root: bool,
):
    """Run the monitor implementation without Typer context."""
    import sys
    import select
    import os
    import time
    from rich.console import Console
    from rich.live import Live

    from im.core import Monitor, SpeedTester, DeviceMonitor, Traffic, render
    from im.platform import get_platform

    console = Console()

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
    # Use screen=True only if we have a proper TTY
    use_screen = sys.stdin.isatty() and sys.stdout.isatty()
    try:
        with Live(render(mon, console, speed, devices, traffic), console=console, screen=use_screen, refresh_per_second=10) as live:
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
    from im.core.render import fmt_duration, fmt_speed, fmt_mb

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


def _show_run_help():
    """Show help for the run command."""
    console = Console()
    console.print("Usage: im run [OPTIONS]")
    console.print("")
    console.print("Start the internet monitor TUI")
    console.print("")
    console.print("Options:")
    console.print("  -i, --interval FLOAT    Check interval in seconds [default: 1.0]")
    console.print("  -t, --timeout FLOAT     Probe timeout in seconds [default: 1.5]")
    console.print("  --duration INT          Stop after N seconds (0 = forever) [default: 0]")
    console.print("  --no-speed              Disable speed test")
    console.print("  --root                  Enable DNS browsing log (needs root/admin)")
    console.print("  --no-install            Skip auto-install, fail if deps missing")
    console.print("  -h, --help              Show this message and exit.")


# Dummy run command just for help
@app.command("run")
def run_cmd(
    help: bool = typer.Option(False, "-h", "--help", help="Show this message and exit"),
):
    """Start the internet monitor TUI."""
    if help:
        _show_run_help()
        raise typer.Exit()
    # Actual execution is handled in callback




@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-v", help="Show version and exit"),
    no_install: bool = typer.Option(False, "--no-install", help="Skip auto-install, fail if deps missing"),
    verbose: bool = typer.Option(False, "--verbose", help="Verbose output"),
):
    """Internet Monitor - Cross-platform connectivity TUI."""
    import sys
    import argparse

    if version:
        console = Console()
        console.print("im v1.0.0 - Internet Monitor")
        raise typer.Exit()

    # Handle 'run' command directly to avoid Typer subcommand invocation issues with Rich Live
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        # Show help for run command
        if "--help" in sys.argv or "-h" in sys.argv:
            _show_run_help()
            raise typer.Exit()

        # Parse run arguments manually
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("-i", "--interval", type=float, default=1.0)
        parser.add_argument("-t", "--timeout", type=float, default=1.5)
        parser.add_argument("--duration", type=int, default=0)
        parser.add_argument("--no-speed", action="store_true")
        parser.add_argument("--root", action="store_true")
        parser.add_argument("--no-install", action="store_true")
        # Parse only known args, ignore unknown
        args, _ = parser.parse_known_args(sys.argv[2:])

        _run_monitor_impl(
            interval=args.interval if args.interval != 1.0 else config.get("interval", 1.0),
            timeout=args.timeout if args.timeout != 1.5 else config.get("timeout", 1.5),
            duration=args.duration if args.duration != 0 else config.get("duration", 0),
            no_speed=args.no_speed or config.get("no_speed", False),
            root=args.root or config.get("root", False),
        )
        raise typer.Exit()

    # If no subcommand provided (just 'im'), run the monitor with auto-install
    if ctx.invoked_subcommand is None:
        _run_with_auto_install(no_install)


def _show_run_help():
    """Show help for the run command."""
    console = Console()
    console.print("Usage: im run [OPTIONS]")
    console.print("")
    console.print("Start the internet monitor TUI")
    console.print("")
    console.print("Options:")
    console.print("  -i, --interval FLOAT    Check interval in seconds [default: 1.0]")
    console.print("  -t, --timeout FLOAT     Probe timeout in seconds [default: 1.5]")
    console.print("  --duration INT          Stop after N seconds (0 = forever) [default: 0]")
    console.print("  --no-speed              Disable speed test")
    console.print("  --root                  Enable DNS browsing log (needs root/admin)")
    console.print("  --no-install            Skip auto-install, fail if deps missing")
    console.print("  -h, --help              Show this message and exit.")


def _run_monitor_impl(
    interval: float,
    timeout: float,
    duration: int,
    no_speed: bool,
    root: bool,
):
    """Run the monitor implementation without Typer context."""
    import sys
    import select
    import os
    import time
    from rich.console import Console
    from rich.live import Live

    from im.core import Monitor, SpeedTester, DeviceMonitor, Traffic, render
    from im.platform import get_platform

    console = Console()

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
    # Use screen=True only if we have a proper TTY
    use_screen = sys.stdin.isatty() and sys.stdout.isatty()
    try:
        with Live(render(mon, console, speed, devices, traffic), console=console, screen=use_screen, refresh_per_second=10) as live:
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
    from im.core.render import fmt_duration, fmt_speed, fmt_mb

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


def _run_with_auto_install(no_install: bool):
    """Run monitor with automatic dependency installation."""
    from rich.console import Console
    from im.installer import get_installer
    from im.cli.pipeline import PipelineRenderer

    console = Console()
    installer = get_installer()
    renderer = PipelineRenderer(console)

    # Run pipeline
    success = renderer.run_pipeline(installer, no_install=no_install)

    if not success:
        if no_install:
            console.print("[red]Missing dependencies. Run 'im install' to install them.[/red]")
        raise typer.Exit(1)

    # Launch monitor
    console.print("[green]🚀  Starting monitor...[/green]")
    time.sleep(0.5)

    _run_monitor_impl(
        interval=config.get("interval", 1.0),
        timeout=config.get("timeout", 1.5),
        duration=config.get("duration", 0),
        no_speed=config.get("no_speed", False),
        root=config.get("root", False),
    )


if __name__ == "__main__":
    app()