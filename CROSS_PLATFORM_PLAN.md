# Cross-Platform netmon.py Implementation Plan

## Current Platform Dependencies

| Feature | Linux/Termux | Windows | macOS |
|---------|--------------|---------|-------|
| Default gateway | `/proc/net/route` | `GetIpForwardTable2` / `route print` | `route -n get default` / `scutil` |
| Interface counters | `/proc/net/dev` | `GetIfTable2` / `netsh` | `netstat -ib` / `ifconfig` |
| ARP/Neighbor table | `/proc/net/arp` + `ip neigh` | `GetIpNetTable2` / `arp -a` | `arp -an` |
| Wi-Fi info | `termux-wifi-connectioninfo` | `netsh wlan show interfaces` / WMI | `airport -I` / `networksetup` |
| DNS sniffing (--root) | `tcpdump` + `su` | Npcap + raw sockets / ETW | `tcpdump` (sudo) |
| Raw keyboard input | `termios`/`tty` | `msvcrt` / `keyboard` lib | `termios`/`tty` |
| Root/Admin check | `su -c id` | `ctypes.windll.shell32.IsUserAnAdmin()` | `os.geteuid() == 0` |

---

## Architecture: Platform Abstraction Layer

```
netmon.py (main)
    │
    ├── platform/
    │   ├── __init__.py          # factory function: get_platform()
    │   ├── base.py              # PlatformInterface (ABC)
    │   ├── linux.py             # LinuxPlatform (current code)
    │   ├── windows.py           # WindowsPlatform
    │   └── macos.py             # MacOSPlatform
    │
    └── (existing Monitor, SpeedTester, DeviceMonitor, Traffic classes)
```

### PlatformInterface (Abstract Base Class)

```python
class PlatformInterface(ABC):
    @abstractmethod
    def get_default_gateway(self) -> str: ...
    
    @abstractmethod
    def get_interface_counters(self) -> Dict[str, Tuple[int, int]]: ...
    
    @abstractmethod
    def get_arp_table(self) -> List[Dict]: ...  # [{ip, mac, state}, ...]
    
    @abstractmethod
    def get_wifi_info(self) -> str: ...  # "SSID (RSSI dBm)" or "-"
    
    @abstractmethod
    def setup_raw_keyboard(self) -> Callable[[], None]: ...  # returns restore fn
    
    @abstractmethod
    def check_admin(self) -> bool: ...
    
    @abstractmethod
    def create_dns_sniffer(self) -> Optional[Iterator[Tuple[str, str]]]: ...
    # yields (source_ip, domain) from DNS traffic
```

---

## Platform-Specific Implementation Details

### LinuxPlatform (Existing - Refactor)
- **Gateway**: Parse `/proc/net/route`
- **Counters**: Parse `/proc/net/dev`
- **ARP**: `ip -f inet neigh show` → fallback `/proc/net/arp`
- **Wi-Fi**: `termux-wifi-connectioninfo` (Termux) → `nmcli -t -f active,ssid,signal dev wifi` (NetworkManager) → `iwconfig`/`iw dev`
- **Keyboard**: `termios`/`tty` (existing)
- **Admin**: `su -c id` (Termux) → `os.geteuid() == 0` (standard Linux)
- **DNS Sniffer**: `tcpdump -i any -n -l -s 0 port 53` via `su` or direct (root)

### WindowsPlatform (New)
**Dependencies**: `psutil` (optional, for interface stats), `wmi` or `pywin32` (for WMI), `Npcap` (for --root)

| Function | Implementation |
|----------|----------------|
| Gateway | `wmi.WMI().Win32_NetworkAdapterConfiguration(IPEnabled=True)[0].DefaultIPGateway[0]` or parse `route print 0.0.0.0` |
| Counters | `psutil.net_io_counters(pernic=True)` (best) or `GetIfTable2` via `ctypes` |
| ARP Table | `GetIpNetTable2` via `ctypes` (IPv4) + `GetIpNetTable2` for IPv6, or parse `arp -a` |
| Wi-Fi | `netsh wlan show interfaces` parsing, or `wmi.WMI().Win32_NetworkAdapterConfiguration` |
| Keyboard | `msvcrt.kbhit()` + `msvcrt.getch()` (stdlib) |
| Admin | `ctypes.windll.shell32.IsUserAnAdmin()` |
| DNS Sniffer | **Option A**: Npcap + `pyshark`/`scapy` (requires Npcap install)<br>**Option B**: ETW (Event Tracing for Windows) - complex<br>**Option C**: Skip on Windows, show "DNS browsing log requires Npcap" |

**Recommended**: Use `psutil` for counters (cross-platform, pure Python wheels). For ARP/gateway/Wi-Fi, use `wmi` (pure Python, no compile) or subprocess parsing as fallback. For DNS sniffing, document Npcap requirement and use `scapy` if available.

### MacOSPlatform (New)
**Dependencies**: Standard Unix tools (all available by default)

| Function | Implementation |
|----------|----------------|
| Gateway | `route -n get default | grep gateway | awk '{print $2}'` or `scutil --dns` |
| Counters | `netstat -ib` parsing or `psutil.net_io_counters(pernic=True)` |
| ARP Table | `arp -an` parsing |
| Wi-Fi | `/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport -I` (parse `agrCtlRSSI`, `SSID`) or `networksetup -getairportnetwork en0` + `airport -I` for RSSI |
| Keyboard | `termios`/`tty` (works natively) |
| Admin | `os.geteuid() == 0` |
| DNS Sniffer | `tcpdump -i any -n -l -s 0 port 53` (needs sudo) |

---

## Implementation Steps

### Phase 1: Create Abstraction Layer
1. Create `platform/base.py` with `PlatformInterface` ABC
2. Create `platform/linux.py` - extract existing Linux/Termux code from netmon.py
3. Create `platform/__init__.py` with `get_platform()` factory
4. Update `netmon.py` to use `platform.get_platform()` instead of direct syscalls

### Phase 2: Windows Implementation
1. Create `platform/windows.py`
2. Implement all abstract methods using WMI/subprocess/psutil
3. Handle `msvcrt` keyboard input
4. Add Npcap detection for DNS sniffer

### Phase 3: macOS Implementation
1. Create `platform/macos.py`
2. Implement all abstract methods using subprocess to system tools
3. Keyboard input works same as Linux

### Phase 4: Integration & Testing
1. Update imports in netmon.py
2. Test on each platform
3. Graceful degradation for missing features (Wi-Fi info, DNS sniffer)
4. Update documentation

---

## Dependencies

### Required (all platforms)
- `rich` (already used)

### Optional but Recommended
- `psutil` - Cross-platform interface counters, CPU, memory. Pure Python wheels available for Win/macOS/Linux. **Highly recommended** - replaces `/proc/net/dev` parsing and `netstat` parsing.

### Platform-Specific
| Platform | Package | Purpose | Install |
|----------|---------|---------|---------|
| Windows | `wmi` | WMI queries (gateway, Wi-Fi, ARP) | `pip install wmi` (requires `pywin32`) |
| Windows | `pywin32` | Windows API access | `pip install pywin32` |
| Windows | `Npcap` | Packet capture for DNS sniffing | Manual: https://npcap.com/ |
| Windows | `scapy` | Packet parsing (if Npcap) | `pip install scapy` |
| macOS | (none) | Uses system tools | N/A |
| Linux | (none) | Uses /proc + ip + termux tools | N/A |

### Minimal Dependency Strategy
If user wants zero extra deps:
- **Linux**: Works out of box
- **macOS**: Works out of box (subprocess to system tools)
- **Windows**: Subprocess parsing of `netsh`, `route`, `arp`, `ipconfig` - no Python packages needed, but more fragile

---

## Acceptance Criteria

### Must Have (All Platforms)
- [ ] `python netmon.py` starts without ImportError
- [ ] Connectivity checks work (TCP probes to 1.1.1.1:443, 8.8.8.8:53)
- [ ] HTTP 204 probe works
- [ ] Speed test download/upload works
- [ ] Timeline renders
- [ ] Probe status renders
- [ ] Statistics render
- [ ] Events render
- [ ] Keyboard controls: `q` quit, `r` reset, `+/-` interval
- [ ] Session summary on exit

### Should Have (Per Platform)
| Feature | Linux | Windows | macOS |
|---------|-------|---------|-------|
| Default gateway display | ✅ | ✅ | ✅ |
| Interface bandwidth (rx/tx) | ✅ | ✅ (psutil) | ✅ (psutil/netstat) |
| Session totals (rx/tx) | ✅ | ✅ | ✅ |
| ARP neighbor list (devices) | ✅ | ✅ | ✅ |
| Wi-Fi SSID + RSSI | ✅ (Termux/nmcli) | ✅ (netsh/WMI) | ✅ (airport) |
| DNS browsing log (--root) | ✅ (su+tcpdump) | ⚠️ (Npcap+Admin) | ✅ (sudo+tcpdump) |

### Graceful Degradation
- If Wi-Fi info unavailable → show "-"
- If ARP table blocked → show note "neighbor table blocked (admin/root needed)"
- If DNS sniffer unavailable → show "browsing log needs Npcap (Windows) / sudo (macOS/Linux)"
- If admin check fails → DNS sniffer disabled, show note

---

## File Changes Summary

### New Files
```
platform/
├── __init__.py
├── base.py
├── linux.py
├── windows.py
└── macos.py
```

### Modified Files
- `netmon.py` - Replace direct platform calls with `platform.get_platform().method()`

### Documentation
- `README.md` - Platform support matrix, Windows Npcap install, macOS sudo
- `requirements.txt` - Core + optional deps

---

## Testing Checklist

### Linux (Debian/Ubuntu/Mint/Arch)
- [ ] Default install (no extra deps)
- [ ] With `psutil` installed
- [ ] Termux on Android
- [ ] With `--root` (root + tcpdump)

### Windows 10/11
- [ ] Default install (subprocess fallback only)
- [ ] With `psutil` + `wmi` + `pywin32`
- [ ] With Npcap + `scapy` for `--root` (Admin)
- [ ] Keyboard controls in cmd.exe, PowerShell, Windows Terminal

### macOS (Intel + Apple Silicon)
- [ ] Default install (no extra deps)
- [ ] With `psutil`
- [ ] With `--root` (sudo + tcpdump)
- [ ] Keyboard controls in Terminal.app, iTerm2

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Windows `netsh` output varies by locale | Medium | High | Use WMI via `wmi` package (locale-independent) |
| `psutil` not installed on some systems | Low | Medium | Fallback to subprocess parsing |
| Npcap not installed on Windows | High | Medium (DNS sniffer only) | Clear error message, degrade gracefully |
| `airport` tool path changes on macOS | Low | Low | Fallback to `networksetup` |
| `termios` not available on Windows | N/A | N/A | Use `msvcrt` branch |
| Subprocess parsing breaks on OS update | Medium | Medium | Prefer `psutil`/`wmi` over parsing |

---

## Estimated Effort

| Phase | Tasks | Est. Hours |
|-------|-------|------------|
| 1. Abstraction Layer | Base class, Linux refactor, factory, integration | 4-6 |
| 2. Windows | Platform class, WMI/psutil, msvcrt keyboard, Npcap detection | 6-8 |
| 3. macOS | Platform class, subprocess tools, integration | 3-4 |
| 4. Testing & Polish | Multi-platform testing, docs, graceful degradation | 4-6 |
| **Total** | | **17-24** |

---

## Quick Start for Implementation

```bash
# 1. Create platform package
mkdir -p platform
touch platform/__init__.py platform/base.py platform/linux.py platform/windows.py platform/macos.py

# 2. Add psutil to requirements (recommended)
echo "rich>=13.0" > requirements.txt
echo "psutil>=5.9" >> requirements.txt  # optional but recommended

# 3. Implement base.py first (ABC), then linux.py (extract from netmon.py)
# 4. Update netmon.py to use platform.get_platform()
# 5. Implement windows.py, macos.py
```