"""TUI rendering functions."""

import time
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn
from typing import Dict, List, Any, Optional


BLOCKS = " ▁▂▃▄▅▆▇█"
NEIGH_LIVE = ("REACHABLE", "DELAY", "PROBE")
DEVICE_ROWS = 6


def fmt_ms(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"{value:.0f} ms" if value < 1000 else f"{value / 1000:.1f} s"


def fmt_speed(mbps: Optional[float]) -> str:
    if mbps is None:
        return "-"
    return f"{mbps * 1000:.0f} kbps" if mbps < 1 else f"{mbps:.1f} Mbps"


def fmt_mb(mbps: Optional[float]) -> str:
    if mbps is None:
        return "-"
    value = mbps / 8.0
    if 0 < value < 0.01:
        return "<0.01 MB/s"
    return f"{value:.2f} MB/s" if value < 10 else f"{value:.1f} MB/s"


def fmt_bytes(value: Optional[float]) -> str:
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


def fmt_duration(seconds: float) -> str:
    seconds = int(max(seconds, 0))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def speed_glyph(mbps: float, scale: float) -> str:
    frac = min(max(mbps / scale, 0.0), 1.0) ** 0.5
    return BLOCKS[1 + int(frac * (len(BLOCKS) - 2))]


def latency_glyph(latency: Optional[float], scale: float) -> str:
    frac = min(max((latency or 0) / scale, 0.0), 1.0)
    return BLOCKS[1 + int(frac * (len(BLOCKS) - 2))]


def status_view(snap: Dict[str, Any]) -> tuple:
    results = snap["results"]
    if not results:
        label, color = "STARTING", "grey62"
    elif snap["up"] and all(ok for ok, _, _ in results.values()):
        label, color = "ONLINE", "green"
    elif snap["up"]:
        label, color = "DEGRADED", "yellow"
    else:
        label, color = "OFFLINE", "red"

    total = snap["total"] or 1
    loss = 100.0 * snap["failed"] / total
    now = time.monotonic()
    line = Text()
    line.append("● ", style=f"bold {color}")
    line.append(label, style=f"bold {color}")
    line.append("   ping ", style="grey62")
    line.append(fmt_ms(snap["avg_lat"]), style="cyan")
    line.append("   loss ", style="grey62")
    line.append(f"{loss:.0f}%", style="red" if loss else "green")
    line.append("   state ", style="grey62")
    line.append(f"{'up' if snap['up'] else 'down'} {fmt_duration(now - snap['changed_at'])}", style="white")
    return line, color


def speed_view(speed: Dict[str, Any]) -> Text:
    line = Text()
    line.append("↓ ", style="grey62")
    line.append(fmt_speed(speed["down"]), style="bold green" if speed["down"] is not None else "grey62")
    line.append(" · ", style="grey37")
    line.append(fmt_mb(speed["down"]), style="green" if speed["down"] is not None else "grey62")
    line.append("   ↑ ", style="grey62")
    line.append(fmt_speed(speed["up"]), style="bold cyan" if speed["up"] is not None else "grey62")
    line.append(" · ", style="grey37")
    line.append(fmt_mb(speed["up"]), style="cyan" if speed["up"] is not None else "grey62")
    if not speed["enabled"]:
        line.append("   speed test off", style="grey62")
        return line
    if speed.get("uploading"):
        line.append("   down paused for upload", style="grey62")
    hist = speed["down_hist"]
    if hist:
        scale = max(max(hist) * 1.15, 1.0)
        line.append("   ")
        for value in hist[-60:]:
            line.append(speed_glyph(value, scale), style="green")
    if speed["down"] is None and speed["errors"]:
        state = "retrying" if hist else "unavailable"
        line.append(f"   down {state} ({speed['errors']} err)", style="red")
    if speed["up"] is None and speed["up_errors"]:
        state = "retrying" if speed["up_hist"] else "unavailable"
        line.append(f"   up {state} ({speed['up_errors']} err)", style="red")
    return line


def info_view(snap: Dict[str, Any]) -> Text:
    line = Text()
    for i, (label, value) in enumerate((
        ("ip", snap["local_ip"]),
        ("gateway", snap["gateway"]),
        ("wi-fi", snap["wifi"]),
        ("session", fmt_duration(time.monotonic() - snap["started"])),
    )):
        if i:
            line.append("   ·   ", style="grey37")
        line.append(f"{label} ", style="grey62")
        line.append(str(value), style="white")
    return line


def devices_view(dev: Dict[str, Any]) -> List[Text]:
    out = []
    entries = dev["entries"]
    live = sum(1 for e in entries if e["state"] in NEIGH_LIVE)
    head = Text()
    head.append("DEVICES", style="grey62")
    head.append(f"   {len(entries)} connected · {live} active", style="white")
    out.append(head)
    if not entries:
        out.append(Text(dev["scan_note"] or "scanning LAN every 10 s…", style="grey62"))
        return out
    for entry in entries[:DEVICE_ROWS]:
        active = entry["state"] in NEIGH_LIVE
        badge = "live" if active else "idle"
        style = "green" if active else "grey62"
        row = Text()
        row.append("● ", style=style)
        row.append(entry["ip"], style="white")
        host = dev["hostnames"].get(entry["ip"])
        if entry["ip"] == dev["gateway"]:
            row.append(" · router", style="grey62")
        elif host:
            row.append(f" · {host[:18]}", style="grey62")
        else:
            row.append(f" · {entry['mac']}", style="grey37")
        row.append(f" · {badge}", style=style)
        if entry["queries"]:
            row.append(f" · {entry['queries']} queries", style="blue")
        row.append(f" · seen {entry['first']}", style="grey37")
        out.append(row)
    if len(entries) > DEVICE_ROWS:
        out.append(Text(f"+{len(entries) - DEVICE_ROWS} more…", style="grey62"))
    out.append(Text(
        "bandwidth aggregates all traffic per interface; exact per-device "
        "bytes need root/admin",
        style="grey37",
    ))
    return out


def iface_view(rows: List[Dict[str, Any]]) -> Text:
    if not rows:
        return Text("interfaces…", style="grey62")
    line = Text()
    for i, row in enumerate(rows):
        if i:
            line.append("   ·   ", style="grey37")
        line.append(f"{row['name']} ", style="white")
        line.append("↓", style="grey62")
        line.append(
            fmt_speed(row["rx_rate"] * 8 / 1e6),
            style="bold green" if row["rx_rate"] > 0 else "green",
        )
        line.append(" ↑", style="grey62")
        line.append(
            fmt_speed(row["tx_rate"] * 8 / 1e6),
            style="bold cyan" if row["tx_rate"] > 0 else "cyan",
        )
        line.append(
            f" ({fmt_bytes(row['rx_session'])}↓/{fmt_bytes(row['tx_session'])}↑)",
            style="grey62",
        )
    return line


def dns_view(dev: Dict[str, Any]) -> List[Text]:
    out = [Text("BROWSING LOG", style="grey62")]
    if dev["dns_log"]:
        for stamp, ip, domain in reversed(dev["dns_log"][-DEVICE_ROWS:]):
            row = Text()
            row.append(f"{stamp} ", style="grey37")
            row.append(ip, style="grey62")
            row.append(f" {domain}", style="blue")
            out.append(row)
    else:
        out.append(Text(dev["dns_note"] or "no queries yet", style="grey62"))
    return out


def timeline_view(snap: Dict[str, Any], width: int) -> Text:
    samples = snap["timeline"]
    if not samples:
        return Text("waiting for first sample…", style="grey62")
    lit = [lat for up, lat in samples if up and lat is not None]
    scale = max(max(lit, default=0) * 1.15, 120)
    text = Text()
    for up, lat in samples[-width:]:
        if not up:
            text.append("▁", style="red")
        elif lat is None:
            text.append("▁", style="green")
        else:
            style = "green" if lat < 150 else "yellow" if lat < 400 else "dark_orange"
            text.append(latency_glyph(lat, scale), style=style)
    return text


def probes_view(snap: Dict[str, Any]) -> Text:
    line = Text()
    results = snap["results"]
    if not results:
        return Text("waiting for first probe…", style="grey62")
    for i, (name, (ok, ms, err)) in enumerate(results.items()):
        if i:
            line.append("   ·   ", style="grey37")
        line.append("✓ " if ok else "✗ ", style="green" if ok else "red")
        line.append(f"{name} ", style="white")
        line.append(fmt_ms(ms) if ok else (err or "fail"), style="grey62")
    return line


def stats_view(snap: Dict[str, Any]) -> Text:
    return Text.assemble(
        ("checks ", "grey62"), (str(snap["total"]), "white"),
        ("   min ", "grey62"), (fmt_ms(snap["min_lat"]), "white"),
        ("   avg ", "grey62"), (fmt_ms(snap["avg_lat"]), "white"),
        ("   max ", "grey62"), (fmt_ms(snap["max_lat"]), "white"),
    )


def events_view(snap: Dict[str, Any]) -> Text:
    events = snap["events"]
    if not events:
        return Text("no state changes yet", style="grey62")
    text = Text()
    for i, (stamp, message) in enumerate(reversed(events)):
        if i:
            text.append("  ·  ", style="grey37")
        color = "green" if "online" in message else "red"
        text.append(f"{stamp} {message}", style=color)
    return text


def render(mon, console: Console, speed, devices, traffic) -> Panel:
    snap = mon.snapshot()
    spd = speed.snapshot()
    dev = devices.snapshot()
    status, color = status_view(snap)
    width = max(console.width - 6, 20)
    body = Group(
        status,
        speed_view(spd),
        info_view(snap),
        Text(""),
        *devices_view(dev),
        iface_view(traffic.snapshot()),
        Text(""),
        Text("TIMELINE", style="grey62"),
        timeline_view(snap, width),
        Text(""),
        probes_view(snap),
        stats_view(snap),
        events_view(snap),
        *dns_view(dev),
    )
    title = Text.assemble(("IM", "bold white"), (" · Internet Monitor", "grey62"))
    subtitle = Text(
        f"q quit · r reset · +/- interval {mon.interval:g}s", style="grey37"
    )
    return Panel(
        body,
        title=title,
        subtitle=subtitle,
        border_style=color,
        padding=(0, 1),
    )