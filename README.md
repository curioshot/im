# im - Internet Monitor

A cross-platform internet connectivity monitor with a beautiful Rich TUI. Works on Linux, Windows, macOS, and Android Termux.

```
im                    # Auto-installs deps, shows pipeline, runs monitor
im doctor             # System diagnostics
im install --check    # Check dependencies
im config --show      # View configuration
```

## Features

- **Cross-platform**: Linux (Debian/Ubuntu/Mint/Arch/Fedora/openSUSE/Alpine), Windows (winget/choco/scoop), macOS (Homebrew), Termux (pkg)
- **Auto-installation**: Runs dependency pipeline with visual progress on first run
- **Rich TUI**: Live connectivity status, latency timeline, speed test, device discovery
- **Continuous monitoring**: TCP probes (Cloudflare, Google DNS), HTTP 204 checks, download/upload speed tests
- **Device tracking**: ARP neighbor scanning with hostnames, first-seen timestamps, DNS query logging (with `--root`)
- **Per-interface bandwidth**: Real-time rx/tx rates with session totals
- **Persistent config**: XDG/APPDATA compatible configuration

## Quick Start

```bash
# Install via pipx (recommended)
pipx install im

# Or install from source
git clone https://github.com/user/im
cd im
pip install -e .

# Run (auto-installs missing dependencies)
im
```

## Commands

| Command | Description |
|---------|-------------|
| `im` | Run monitor with auto-install pipeline |
| `im run` | Run monitor directly |
| `im run --no-speed` | Latency only (no data usage) |
| `im run --duration 60` | Run for 60 seconds |
| `im run --root` | Enable DNS browsing log (needs root/admin) |
| `im install` | Install/check dependencies with visual pipeline |
| `im install --check` | Check only, don't install |
| `im doctor` | Full system diagnostics |
| `im config --show` | Show configuration |
| `im config --set interval=2.0` | Set config value |
| `im --version` | Show version |

## Screenshots

```
╭─────────────────────────────────────────────────────────────╮
│  🌐  im - Internet Monitor  v1.0.0                          │
│  📦  Platform: Linux (Debian 13)                            │
├─────────────────────────────────────────────────────────────┤
│  🔍  Checking Dependencies...                               │
│  ✅  rich        ❌  psutil      ❌  iproute2               │
├─────────────────────────────────────────────────────────────┤
│  📥  Installing...  ████████████░░░░░░░░░░  45%  rich       │
├─────────────────────────────────────────────────────────────┤
│  ✅  All dependencies satisfied!  🚀  Starting monitor...   │
╰─────────────────────────────────────────────────────────────╯
```

Monitor TUI:
```
╭──────────────── IM · Internet Monitor ─────────────────────╮
│ ● ONLINE   ping 12 ms   loss 0%   state up 00:02:34        │
│ ↓ 12.5 Mbps · 1.56 MB/s   ↑ 5.2 Mbps · 0.65 MB/s           │
│ ip 192.168.1.50   ·   gateway 192.168.1.1   ·   wifi -     │
│                                                             │
│ DEVICES   3 connected · 2 active                            │
│ ● 192.168.1.1 · router · live · seen 10:15:23              │
│ ● 192.168.1.50 · laptop · live · 5 queries · seen 10:15:23 │
│                                                             │
│ enp2s0 ↓12.5 Mbps ↑5.2 Mbps (1.2 GB↓/500 MB↑)              │
│                                                             │
│ TIMELINE                                                    │
│ ▂▃▅▆▇▅▃▂▁▂▃▄▅▆▇█▇▆▅▄▃▂▁                                    │
│                                                             │
│ ✓ Cloudflare 12 ms   ✓ Google DNS 8 ms   ✓ HTTP 204 15 ms │
│ checks 150   min 8 ms   avg 12 ms   max 45 ms              │
│ 10:30:15 back online  ·  10:25:00 connection lost          │
│                                                             │
│ BROWSING LOG                                                │
│ 10:31:22 192.168.1.50 github.com                           │
│ 10:31:18 192.168.1.50 api.github.com                       │
╰─────────────────────────────────────────────────────────────╯
q quit · r reset · +/- interval 1.0s
```

## Installation

### pipx (recommended)
```bash
pipx install im
```

### From source
```bash
git clone https://github.com/user/im
cd im
pip install -e .
```

### Platform-specific notes

**Linux**: Works out of the box. For DNS browsing log (`--root`), install `tcpdump` and run with `sudo` or `su`.

**Windows**: Uses `winget` (built-in), `choco`, or `scoop` for system packages. For DNS browsing log, installs Npcap automatically (requires Admin).

**macOS**: Requires Homebrew. Install with `brew install im` (tap needed) or from source. DNS browsing log needs `sudo tcpdump`.

**Termux**: Works with `pkg`. Enhanced with `termux-api` for Wi-Fi info and `su` for root features.

## Configuration

Config file: `~/.config/im/config.json` (Linux/macOS) or `%APPDATA%\im\config.json` (Windows)

```json
{
  "interval": 1.0,
  "timeout": 1.5,
  "duration": 0,
  "no_speed": false,
  "root": false,
  "theme": "default"
}
```

## Architecture

```
im/
├── cli/                    # CLI layer (Typer + Rich)
│   ├── commands/           # run, install, doctor, config, update
│   └── pipeline.py         # Visual installation pipeline
├── platform/               # Platform abstraction
│   ├── base.py             # Abstract interface
│   ├── linux.py            # Linux implementation
│   ├── windows.py          # Windows implementation
│   ├── macos.py            # macOS implementation
│   └── termux.py           # Termux implementation
├── installer/              # Dependency installers
│   ├── base.py             # Abstract interface
│   ├── linux.py            # apt/dnf/pacman/zypper/apk
│   ├── windows.py          # winget/choco/scoop + Npcap
│   ├── macos.py            # Homebrew
│   └── termux.py           # pkg
└── core/                   # Monitoring logic
    ├── monitor.py          # Monitor, SpeedTester, DeviceMonitor, Traffic
    ├── render.py           # Rich TUI rendering
    └── config.py           # Persistent configuration
```

## Dependencies

**Python** (auto-installed):
- `rich` - TUI rendering
- `typer` - CLI framework
- `psutil` - Cross-platform system info (optional but recommended)
- `distro` - Linux distribution detection

**System** (auto-installed via platform package manager):
- Linux: `iproute2`, `tcpdump` (optional), `network-manager` (optional)
- Windows: Npcap (for `--root`)
- macOS: `tcpdump` (for `--root`)

## Development

```bash
# Install dev dependencies
pip install -e .[dev]

# Run tests
pytest

# Lint
ruff check .
```

## License

MIT License - see [LICENSE](LICENSE) for details.