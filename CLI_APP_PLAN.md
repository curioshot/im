# "im" (Internet Monitor) - Cross-Platform CLI Application Plan

## Vision

```
$ im                    # Runs internet monitor on ANY platform
$ im --help             # Shows help
$ im install            # Installs/updates dependencies for current OS
$ im doctor             # Diagnoses system readiness
$ im --version          # Shows version
```

**Goal**: Single command `im` that auto-detects OS, installs missing dependencies (Python packages + system tools), shows a visual pipeline, then launches the TUI.

---

## Architecture Overview

```
im (entry point)           # pipx/pip installable, or standalone binary
    │
    ├── cli/
    │   ├── __main__.py          # Click/Typer CLI entry point
    │   ├── commands/
    │   │   ├── run.py           # Main monitor command
    │   │   ├── install.py       # Dependency installer
    │   │   ├── doctor.py        # System diagnostics
    │   │   └── update.py        # Self-update
    │   └── pipeline.py          # Visual pipeline renderer
    │
    ├── platform/                # (from previous plan)
    │   ├── __init__.py
    │   ├── base.py
    │   ├── linux.py
    │   ├── windows.py
    │   └── macos.py
    │
    ├── core/                    # Existing monitor logic
    │   ├── monitor.py           # Monitor, SpeedTester, DeviceMonitor, Traffic
    │   ├── render.py            # Rich TUI rendering
    │   └── config.py            # Configuration management
    │
    ├── installer/               # Cross-platform dependency installer
    │   ├── __init__.py
    │   ├── base.py              # InstallerInterface (ABC)
    │   ├── linux.py             # apt/dnf/pacman + pip
    │   ├── windows.py           # winget/choco/scoop + pip
    │   ├── macos.py             # brew + pip
    │   └── termux.py            # pkg + pip
    │
    └── packaging/
        ├── pyproject.toml       # Modern Python packaging
        ├── build.py             # PyInstaller/Nuitka build script
        └── install.sh           # Universal installer script
```

---

## CLI Command Structure

```bash
im [OPTIONS] COMMAND [ARGS]...

Commands:
  run          Start internet monitor (default command)
  install      Install/check dependencies for current platform
  doctor       Show system diagnostics & readiness
  update       Update im to latest version
  uninstall    Remove im and dependencies
  config       Manage configuration

Options:
  -i, --interval FLOAT    Check interval in seconds (default: 1.0)
  -t, --timeout FLOAT     Probe timeout in seconds (default: 1.5)
  --duration INT          Stop after N seconds (default: 0 = forever)
  --no-speed              Disable speed test
  --root                  Enable DNS browsing log (needs root/Admin)
  --no-install            Skip auto-install, fail if deps missing
  -v, --verbose           Verbose output
  --version               Show version and exit
  -h, --help              Show help

Examples:
  im                      # Run with defaults
  im run -i 0.5           # Faster checks
  im run --no-speed       # Latency only
  im install              # Install dependencies
  im doctor               # Check system readiness
```

---

## Auto-Install Pipeline (Visual)

When user runs `im` (or `im run`) without dependencies:

```
╭─────────────────────────────────────────────────────────────╮
│  🌐  im - Internet Monitor  v1.0.0                          │
│  📦  Detecting platform...  Linux (Debian 12)               │
├─────────────────────────────────────────────────────────────┤
│  🔍  Checking dependencies...                               │
│                                                             │
│  ✅  Python 3.11+              [3.12.3]                     │
│  ❌  rich                       [NOT FOUND]                 │
│  ❌  psutil                     [NOT FOUND]                 │
│  ❌  iproute2 (ip)              [NOT FOUND]                 │
│  ⚠️  tcpdump (for --root)       [NOT FOUND]                 │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  📥  Installing missing dependencies...                     │
│                                                             │
│  ████████████░░░░░░░░░░  45%  Installing rich via pip      │
│  ████████████████████░░░░  72%  Installing psutil via pip  │
│  ████████████████████████  100%  Installing iproute2 apt   │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  ✅  All dependencies satisfied!                            │
│  🚀  Starting monitor...                                    │
╰─────────────────────────────────────────────────────────────╯
```

### Pipeline Stages

| Stage | Description | Tools |
|-------|-------------|-------|
| **Detect** | Identify OS, distro, Python version, architecture | `platform`, `distro`, `sys` |
| **Check** | Verify each required dependency (Python + system) | `importlib`, `shutil.which`, package managers |
| **Plan** | Build install plan per dependency type | Platform-specific logic |
| **Install** | Execute installs with progress bars | `subprocess`, `pip`, package managers |
| **Verify** | Re-check all dependencies post-install | Same as Check |
| **Launch** | Start the monitor TUI | `core.monitor.run()` |

---

## Dependency Matrix by Platform

### Python Packages (All Platforms)

| Package | Required | Purpose | Install Method |
|---------|----------|---------|----------------|
| `rich` | ✅ Yes | TUI rendering | `pip install rich` |
| `psutil` | ⚠️ Recommended | Cross-platform interface stats | `pip install psutil` |
| `click` / `typer` | ✅ Yes | CLI framework | `pip install typer` |
| `distro` | ✅ Yes | Linux distro detection | `pip install distro` |

### System Tools by Platform

| Tool | Linux (Debian/Ubuntu/Mint) | Linux (Arch) | Linux (Fedora/RHEL) | Termux | Windows | macOS |
|------|---------------------------|--------------|---------------------|--------|---------|-------|
| `ip` (iproute2) | `apt install iproute2` | `pacman -S iproute2` | `dnf install iproute2` | `pkg install iproute2` | N/A | N/A |
| `tcpdump` | `apt install tcpdump` | `pacman -S tcpdump` | `dnf install tcpdump` | `pkg install tcpdump` | **Npcap** | `brew install tcpdump` |
| `netsh` | N/A | N/A | N/A | N/A | Built-in | N/A |
| `wmi`/`pywin32` | N/A | N/A | N/A | N/A | `pip install wmi pywin32` | N/A |
| `airport` | N/A | N/A | N/A | N/A | N/A | Built-in (private framework) |
| `nmcli` | `apt install network-manager` | `pacman -S networkmanager` | `dnf install NetworkManager` | N/A | N/A | N/A |

### Windows Special: Npcap for DNS Sniffing

```
⚠️  DNS browsing log (--root) requires Npcap on Windows
    Download: https://npcap.com/#download
    Install with: "Install Npcap in WinPcap API-compatible Mode"
    Then: pip install scapy
```

---

## Installer Architecture

### InstallerInterface (ABC)

```python
class InstallerInterface(ABC):
    @abstractmethod
    def detect_platform(self) -> PlatformInfo: ...
    
    @abstractmethod
    def check_python_deps(self) -> Dict[str, bool]: ...
    
    @abstractmethod
    def check_system_deps(self) -> Dict[str, bool]: ...
    
    @abstractmethod
    def install_python_dep(self, package: str) -> bool: ...
    
    @abstractmethod
    def install_system_dep(self, tool: str) -> bool: ...
    
    @abstractmethod
    def get_package_manager(self) -> str: ...  # "apt", "dnf", "pacman", "winget", "brew", "pkg"
    
    @abstractmethod
    def supports_auto_install(self) -> bool: ...
```

### Platform-Specific Implementations

#### LinuxInstaller (Debian/Ubuntu/Mint/Arch/Fedora/etc.)
- Detects distro via `distro.id()`
- Maps tools to packages per distro
- Uses `apt`/`dnf`/`pacman`/`zypper`/`apk` with `sudo`
- Falls back to `pip` for Python packages

#### TermuxInstaller
- Uses `pkg` (no sudo needed)
- Python packages via `pip`
- Special handling for `su` availability

#### WindowsInstaller
- **Priority 1**: `winget` (built-in Windows 10/11)
- **Priority 2**: `choco` (Chocolatey)
- **Priority 3**: `scoop`
- Python packages via `pip`
- **Admin check**: Elevate if needed for system packages
- **Npcap**: Special handler - downloads installer, runs silently

#### MacOSInstaller
- **Homebrew** (required - prompts to install if missing)
- `brew install tcpdump iproute2mac` (for `ip` command alternative)
- Python packages via `pip`
- **sudo** for `tcpdump` DNS sniffing

---

## Distribution Strategies

### Strategy 1: PyPI + pipx (Recommended for Python users)

```bash
# User installs once
pipx install im

# Or with pip (less isolated)
pip install im

# Then runs anywhere
im
```

**Pros**: Standard Python packaging, auto-updates via `pipx upgrade im`, works on all platforms with Python
**Cons**: Requires Python + pipx installed first

### Strategy 2: Standalone Binaries (Best for end users)

Build with **PyInstaller** or **Nuitka**:

```
dist/
├── im-linux-x86_64       # Linux x64
├── im-linux-aarch64      # Linux ARM64 (Pi, Termux)
├── im-windows-x86_64.exe # Windows x64
├── im-windows-arm64.exe  # Windows ARM64
├── im-macos-x86_64       # macOS Intel
└── im-macos-arm64        # macOS Apple Silicon
```

**Pros**: Zero dependencies, single file, runs on machines without Python
**Cons**: Larger binary (~15-30MB), needs CI for multi-platform builds

### Strategy 3: Universal Installer Script

```bash
curl -fsSL https://github.com/user/im/releases/latest/download/install.sh | bash
```

Downloads correct binary for platform, installs to `~/.local/bin` or `/usr/local/bin`.

### Strategy 4: Platform Package Managers

| Platform | Package | Command |
|----------|---------|---------|
| Arch Linux | AUR | `yay -S im` |
| Homebrew | tap | `brew install user/tap/im` |
| Chocolatey | choco | `choco install im` |
| Scoop | scoop | `scoop install im` |
| Winget | winget | `winget install im` |
| Termux | pkg | `pkg install im` (needs PR to termux-packages) |

---

## Implementation Plan

### Phase 1: Core CLI & Pipeline (Week 1-2)

| Task | Details |
|------|---------|
| 1.1 | Create `pyproject.toml` with `typer`, `rich`, `psutil`, `distro` |
| 1.2 | Build `cli/__main__.py` with Typer app, commands |
| 1.3 | Implement `cli/pipeline.py` - Rich Live progress display |
| 1.4 | Create `PlatformInfo` dataclass (os, distro, arch, python_version, has_sudo, has_admin) |
| 1.5 | Implement `installer/base.py` (ABC) + `installer/linux.py` |
| 1.6 | Wire `install` command to run pipeline |
| 1.7 | Modify `netmon.py` → `core/monitor.py` (refactor for import) |
| 1.8 | `run` command launches monitor with CLI args |

### Phase 2: Windows & macOS Installers (Week 2-3)

| Task | Details |
|------|---------|
| 2.1 | `installer/windows.py` - winget/choco/scoop detection |
| 2.2 | Windows Npcap downloader + silent installer |
| 2.3 | Windows Admin elevation (UAC) for system packages |
| 2.4 | `installer/macos.py` - Homebrew detection + install |
| 2.5 | macOS `airport` tool path detection |
| 2.6 | `installer/termux.py` - pkg wrapper |
| 2.7 | Cross-platform test matrix |

### Phase 3: Packaging & Distribution (Week 3-4)

| Task | Details |
|------|---------|
| 3.1 | PyInstaller spec for each platform |
| 3.2 | GitHub Actions workflow for multi-platform builds |
| 3.3 | Release automation (tag → build → release) |
| 3.4 | Universal `install.sh` script |
| 3.5 | Homebrew tap / Chocolatey / Scoop manifests |
| 3.6 | Documentation: README, man page, shell completions |

### Phase 4: Polish & Advanced Features (Week 4-5)

| Task | Details |
|------|---------|
| 4.1 | `doctor` command - full system diagnostics |
| 4.2 | `config` command - persistent settings (YAML/TOML) |
| 4.3 | Shell completions (bash, zsh, fish, PowerShell) |
| 4.4 | Auto-update check (background, non-blocking) |
| 4.5 | Telemetry opt-in (anonymous usage stats) |
| 4.6 | Man page generation |

---

## pyproject.toml (Modern Packaging)

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "im"
version = "1.0.0"
description = "Internet Monitor - Cross-platform connectivity TUI"
readme = "README.md"
license = {text = "MIT"}
requires-python = ">=3.9"
dependencies = [
    "rich>=13.7",
    "typer>=0.9",
    "psutil>=5.9",
    "distro>=1.8",
]
optional-dependencies = {
    "windows" = ["wmi>=1.5", "pywin32>=306"],
    "dev" = ["pytest", "ruff", "pyinstaller", "nuitka"],
}

[project.entry-points]
console_scripts = [
    "im = cli.__main__:app",
]

[project.urls]
Homepage = "https://github.com/user/im"
Repository = "https://github.com/user/im"
Issues = "https://github.com/user/im/issues"

[tool.setuptools.packages.find]
where = ["."]
include = ["cli*", "core*", "platform*", "installer*"]

[tool.pyinstaller]
# PyInstaller config for standalone binaries
```

---

## Pipeline Implementation (Rich)

```python
# cli/pipeline.py
from rich.live import Live
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn
from rich.panel import Panel
from rich.text import Text

class PipelineRenderer:
    def __init__(self, console):
        self.console = console
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
            console=console,
        )
    
    def render_stage(self, stage: str, items: List[PipelineItem]):
        task = self.progress.add_task(stage, total=len(items))
        for item in items:
            self.progress.update(task, description=f"{item.icon} {item.name}")
            item.execute()
            self.progress.advance(task)
```

---

## Acceptance Criteria

### MVP (Minimum Viable Product)
- [ ] `pipx install im` works on Linux/macOS/Windows
- [ ] `im` command auto-detects platform
- [ ] `im install` installs Python deps via pip
- [ ] `im install` installs system deps via package manager (Linux/macOS/Termux)
- [ ] `im run` launches monitor TUI
- [ ] Pipeline shows visual progress for each stage
- [ ] Graceful degradation if optional deps missing

### Full Release
- [ ] Standalone binaries for all 6 targets (linux-x64, linux-arm64, windows-x64, windows-arm64, macos-x64, macos-arm64)
- [ ] `im doctor` shows comprehensive diagnostics
- [ ] `im config` manages persistent settings
- [ ] Shell completions generated
- [ ] Auto-update notification
- [ ] Windows: Npcap auto-download + install for `--root`
- [ ] Windows: UAC elevation for system packages
- [ ] macOS: Homebrew auto-install prompt
- [ ] Termux: Works without root, enhanced with root

### Quality Gates
- [ ] CI builds on every push (GitHub Actions matrix)
- [ ] Binary size < 30MB (compressed)
- [ ] Cold start < 2s (binary), < 3s (pipx)
- [ ] Zero runtime dependencies (standalone binary)
- [ ] Works offline after install (except speed test)

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Package manager not installed (brew, winget) | Medium | High | Detect & prompt install; fallback to manual instructions |
| No sudo/Admin rights | High | Medium | Degrade gracefully; show what needs manual install |
| Python version < 3.9 | Low | High | Check early; clear error with upgrade instructions |
| Network blocked (corporate firewall) | Medium | Medium | Offline mode; cache downloads; --no-install flag |
| Antivirus flags PyInstaller binary | Medium | Low | Code signing; use Nuitka as alternative |
| Distro not recognized | Low | Medium | Fallback to generic Linux; community PRs |
| `pip` not in PATH | Medium | High | Use `sys.executable -m pip` |

---

## File Structure (Final)

```
im/
├── pyproject.toml
├── README.md
├── LICENSE
├── install.sh                 # Universal installer
├── build.py                   # Build script
├── cli/
│   ├── __init__.py
│   ├── __main__.py            # Typer app entry point
│   ├── pipeline.py            # Visual pipeline renderer
│   └── commands/
│       ├── __init__.py
│       ├── run.py
│       ├── install.py
│       ├── doctor.py
│       ├── update.py
│       └── config.py
├── core/
│   ├── __init__.py
│   ├── monitor.py             # Monitor, SpeedTester, DeviceMonitor, Traffic
│   ├── render.py              # TUI rendering functions
│   └── config.py              # Config management
├── platform/
│   ├── __init__.py
│   ├── base.py
│   ├── linux.py
│   ├── windows.py
│   └── macos.py
├── installer/
│   ├── __init__.py
│   ├── base.py
│   ├── linux.py
│   ├── windows.py
│   ├── macos.py
│   └── termux.py
└── packaging/
    ├── pyinstaller.spec
    ├── nuitka.toml
    └── github-actions/
        └── build.yml
```

---

## Quick Start for Implementation

```bash
# 1. Initialize project structure
mkdir -p im/{cli/commands,core,platform,installer,packaging/github-actions}
touch im/cli/__init__.py im/cli/commands/__init__.py
touch im/core/__init__.py im/platform/__init__.py im/installer/__init__.py

# 2. Create pyproject.toml (see above)

# 3. Move existing netmon.py → im/core/monitor.py (refactor for imports)

# 4. Build CLI entry point (cli/__main__.py) with Typer

# 5. Implement pipeline renderer (cli/pipeline.py)

# 6. Create Linux installer first (most straightforward)

# 7. Test: pip install -e . && im install && im run
```

---

## Estimated Effort

| Phase | Tasks | Est. Hours |
|-------|-------|------------|
| 1. Core CLI & Pipeline | Project setup, Typer, pipeline, Linux installer, refactor | 16-24 |
| 2. Windows/macOS/Termux | 3 platform installers, Npcap, UAC, Homebrew | 16-20 |
| 3. Packaging & CI | PyInstaller/Nuitka, GitHub Actions, release automation | 12-16 |
| 4. Polish | doctor, config, completions, auto-update, docs | 8-12 |
| **Total** | | **52-72** |

---

## Success Metrics

- **Install success rate**: >95% on clean VMs per platform
- **Time to first TUI**: <30s (including deps install)
- **Binary portability**: Runs on glibc 2.17+ (Linux), Windows 10+, macOS 11+
- **User friction**: Single command `im` works everywhere