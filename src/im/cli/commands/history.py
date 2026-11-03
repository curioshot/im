"""History command - view and export historical data."""

import time
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from typing import Optional
from datetime import datetime, timedelta

from ...core.history import get_history_manager, CheckRecord, SpeedRecord, DeviceRecord, EventRecord
from ...core.config import config


app = typer.Typer(name="history", help="View and export historical data")


def _parse_time(time_str: str) -> Optional[float]:
    """Parse time string like '1h', '30m', '7d' or ISO format."""
    if not time_str:
        return None
    
    time_str = time_str.lower().strip()
    if time_str.endswith('s'):
        return time.time() - float(time_str[:-1])
    elif time_str.endswith('m'):
        return time.time() - float(time_str[:-1]) * 60
    elif time_str.endswith('h'):
        return time.time() - float(time_str[:-1]) * 3600
    elif time_str.endswith('d'):
        return time.time() - float(time_str[:-1]) * 86400
    else:
        # Try ISO format
        try:
            dt = datetime.fromisoformat(time_str)
            return dt.timestamp()
        except ValueError:
            return None


@app.command("checks")
def show_checks(
    limit: int = typer.Option(50, "-n", "--limit", help="Number of records"),
    since: str = typer.Option("", "--since", help="Show records since (e.g. 1h, 7d, ISO date)"),
    until: str = typer.Option("", "--until", help="Show records until (e.g. 1h, 7d, ISO date)"),
    up_only: bool = typer.Option(False, "--up", help="Show only successful checks"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show connectivity check history."""
    console = Console()
    hm = get_history_manager()
    
    since_ts = _parse_time(since)
    until_ts = _parse_time(until)
    
    checks = hm.get_checks(since=since_ts, until=until_ts, limit=limit, up_only=up_only)
    
    if json_output:
        import json
        console.print_json(json.dumps([{
            'timestamp': c.timestamp,
            'datetime': datetime.fromtimestamp(c.timestamp).isoformat(),
            'up': c.up,
            'latency_ms': c.latency_ms,
            'probe_results': c.probe_results
        } for c in checks]))
        return
    
    if not checks:
        console.print("[yellow]No check records found[/yellow]")
        return
    
    table = Table(title=f"Connectivity Checks (last {len(checks)})", show_header=True)
    table.add_column("Time", style="dim")
    table.add_column("Status", justify="center")
    table.add_column("Latency", justify="right")
    table.add_column("Probes")
    
    for c in checks:
        dt = datetime.fromtimestamp(c.timestamp).strftime('%H:%M:%S')
        status = "✅ UP" if c.up else "❌ DOWN"
        status_style = "green" if c.up else "red"
        latency = f"{c.latency_ms:.0f}ms" if c.latency_ms else "N/A"
        
        # Parse probe results
        try:
            probes = json.loads(c.probe_results)
            probe_str = ", ".join([f"{k}:{'✓' if v.get('success') else '✗'}" for k, v in probes.items()])
        except:
            probe_str = "N/A"
        
        table.add_row(
            dt,
            Text(status, style=status_style),
            latency,
            probe_str
        )
    
    console.print(table)


@app.command("speed")
def show_speed(
    limit: int = typer.Option(50, "-n", "--limit", help="Number of records"),
    since: str = typer.Option("", "--since", help="Show records since (e.g. 1h, 7d)"),
    until: str = typer.Option("", "--until", help="Show records until"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show speed test history."""
    console = Console()
    hm = get_history_manager()
    
    since_ts = _parse_time(since)
    until_ts = _parse_time(until)
    
    speeds = hm.get_speed_tests(since=since_ts, until=until_ts, limit=limit)
    
    if json_output:
        import json
        console.print_json(json.dumps([{
            'timestamp': s.timestamp,
            'datetime': datetime.fromtimestamp(s.timestamp).isoformat(),
            'download_mbps': s.download_mbps,
            'upload_mbps': s.upload_mbps
        } for s in speeds]))
        return
    
    if not speeds:
        console.print("[yellow]No speed test records found[/yellow]")
        return
    
    table = Table(title=f"Speed Tests (last {len(speeds)})", show_header=True)
    table.add_column("Time", style="dim")
    table.add_column("Download", justify="right")
    table.add_column("Upload", justify="right")
    
    for s in speeds:
        dt = datetime.fromtimestamp(s.timestamp).strftime('%H:%M:%S')
        down = f"{s.download_mbps:.1f} Mbps" if s.download_mbps else "N/A"
        up = f"{s.upload_mbps:.1f} Mbps" if s.upload_mbps else "N/A"
        
        table.add_row(dt, down, up)
    
    console.print(table)


@app.command("devices")
def show_devices(
    limit: int = typer.Option(50, "-n", "--limit", help="Number of records"),
    since: str = typer.Option("", "--since", help="Show records since"),
    until: str = typer.Option("", "--until", help="Show records until"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show device discovery history."""
    console = Console()
    hm = get_history_manager()
    
    since_ts = _parse_time(since)
    until_ts = _parse_time(until)
    
    devices = hm.get_devices(since=since_ts, until=until_ts, limit=limit)
    
    if json_output:
        import json
        console.print_json(json.dumps([{
            'timestamp': d.timestamp,
            'datetime': datetime.fromtimestamp(d.timestamp).isoformat(),
            'ip': d.ip,
            'mac': d.mac,
            'hostname': d.hostname,
            'state': d.state,
            'is_gateway': d.is_gateway
        } for d in devices]))
        return
    
    if not devices:
        console.print("[yellow]No device records found[/yellow]")
        return
    
    table = Table(title=f"Device History (last {len(devices)})", show_header=True)
    table.add_column("Time", style="dim")
    table.add_column("IP", style="cyan")
    table.add_column("MAC", style="dim")
    table.add_column("Hostname")
    table.add_column("State")
    table.add_column("Gateway", justify="center")
    
    for d in devices:
        dt = datetime.fromtimestamp(d.timestamp).strftime('%H:%M:%S')
        state_style = "green" if d.state in ("REACHABLE", "DELAY", "PROBE") else "red"
        gateway = "✓" if d.is_gateway else ""
        
        table.add_row(
            dt,
            d.ip,
            d.mac,
            d.hostname or "-",
            Text(d.state, style=state_style),
            gateway
        )
    
    console.print(table)


@app.command("events")
def show_events(
    limit: int = typer.Option(50, "-n", "--limit", help="Number of records"),
    since: str = typer.Option("", "--since", help="Show records since"),
    until: str = typer.Option("", "--until", help="Show records until"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show state change events."""
    console = Console()
    hm = get_history_manager()
    
    since_ts = _parse_time(since)
    until_ts = _parse_time(until)
    
    events = hm.get_events(since=since_ts, until=until_ts, limit=limit)
    
    if json_output:
        import json
        console.print_json(json.dumps([{
            'timestamp': e.timestamp,
            'datetime': datetime.fromtimestamp(e.timestamp).isoformat(),
            'type': e.event_type,
            'message': e.message
        } for e in events]))
        return
    
    if not events:
        console.print("[yellow]No events found[/yellow]")
        return
    
    for e in events:
        dt = datetime.fromtimestamp(e.timestamp).strftime('%H:%M:%S')
        color = "green" if e.event_type in ("up", "back") else "red"
        console.print(Text(f"[{dt}] ", style="dim") + 
                     Text(f"{e.event_type.upper()}: ", style=f"bold {color}") + 
                     Text(e.message))


@app.command("stats")
def show_stats(
    since: str = typer.Option("24h", "--since", help="Time period for stats (default 24h)"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show summary statistics."""
    console = Console()
    hm = get_history_manager()
    
    since_ts = _parse_time(since)
    stats = hm.get_stats(since=since_ts)
    
    if json_output:
        import json
        console.print_json(json.dumps(stats))
        return
    
    # Checks
    checks = stats.get('checks', {})
    if checks:
        panel_content = Text()
        panel_content.append("Total: ", style="dim")
        panel_content.append(f"{checks.get('total', 0)}\n", style="white")
        panel_content.append("Up: ", style="dim")
        panel_content.append(f"{checks.get('up_count', 0)} ({checks.get('up_count', 0)/max(1,checks.get('total',1))*100:.1f}%)\n", style="green")
        panel_content.append("Avg Latency: ", style="dim")
        panel_content.append(f"{checks.get('avg_latency_ms', 0):.1f}ms\n", style="cyan")
        panel_content.append("Min/Max: ", style="dim")
        panel_content.append(f"{checks.get('min_latency_ms', 0):.0f}/{checks.get('max_latency_ms', 0):.0f}ms", style="white")
        console.print(Panel(panel_content, title="📊 Connectivity Checks", border_style="blue"))
    
    # Speed
    speed = stats.get('speed', {})
    if speed and speed.get('total', 0) > 0:
        panel_content = Text()
        panel_content.append("Tests: ", style="dim")
        panel_content.append(f"{speed.get('total', 0)}\n", style="white")
        panel_content.append("Avg Download: ", style="dim")
        panel_content.append(f"{speed.get('avg_down', 0):.1f} Mbps\n", style="green")
        panel_content.append("Max Download: ", style="dim")
        panel_content.append(f"{speed.get('max_down', 0):.1f} Mbps\n", style="white")
        panel_content.append("Avg Upload: ", style="dim")
        panel_content.append(f"{speed.get('avg_up', 0):.1f} Mbps\n", style="cyan")
        panel_content.append("Max Upload: ", style="dim")
        panel_content.append(f"{speed.get('max_up', 0):.1f} Mbps", style="white")
        console.print(Panel(panel_content, title="📈 Speed Tests", border_style="green"))
    
    # Devices
    devices = stats.get('devices', {})
    if devices:
        console.print(Panel(
            f"Unique devices: {devices.get('unique_devices', 0)}",
            title="📱 Devices", border_style="yellow"
        ))
    
    # Events
    events = stats.get('events', {})
    if events:
        event_text = Text()
        for event_type, count in events.items():
            color = "green" if event_type in ("up", "back") else "red"
            event_text.append(f"{event_type}: {count}  ", style=color)
        console.print(Panel(event_text, title="🔔 Events", border_style="yellow"))


@app.command("export")
def export_data(
    format: str = typer.Option("json", "--format", help="Export format: json, csv"),
    since: str = typer.Option("24h", "--since", help="Export data since"),
    until: str = typer.Option("", "--until", help="Export data until"),
    output: str = typer.Option("-", "--output", "-o", help="Output file (- for stdout)"),
):
    """Export historical data."""
    hm = get_history_manager()
    
    since_ts = _parse_time(since)
    until_ts = _parse_time(until)
    
    data = hm.export(format=format, since=since_ts, until=until_ts)
    
    if output == "-":
        print(data)
    else:
        with open(output, 'w') as f:
            f.write(data)
        print(f"Exported to {output}")


@app.command("cleanup")
def cleanup(
    days: int = typer.Option(30, "--days", help="Keep data newer than N days"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Remove old historical data."""
    if not force:
        console = Console()
        confirm = console.input(f"[yellow]Delete data older than {days} days? [y/N]: [/yellow]")
        if confirm.lower() != 'y':
            print("Cancelled")
            return
    
    hm = get_history_manager()
    hm.cleanup_old(days)
    print(f"Cleaned up data older than {days} days")


if __name__ == "__main__":
    app()