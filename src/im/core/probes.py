"""Extended probing capabilities for im."""

import socket
import ssl
import time
import threading
import subprocess
import re
from typing import Dict, List, Optional, Tuple, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, Future
import ipaddress

# Optional DNS dependencies
try:
    import dns.resolver
    import dns.message
    import dns.query
    import dns.flags
    HAS_DNS = True
except ImportError:
    HAS_DNS = False


class ProbeType(Enum):
    TCP = "tcp"
    UDP = "udp"
    ICMP = "icmp"
    DNS = "dns"
    DOH = "doh"
    DOT = "dot"
    HTTP = "http"
    HTTPS = "https"
    TLS = "tls"


@dataclass
class ProbeResult:
    """Result of a probe."""
    probe_type: ProbeType
    target: str
    success: bool
    latency_ms: Optional[float]
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseProbe(ABC):
    """Base class for probes."""
    
    def __init__(self, timeout: float = 5.0):
        self.timeout = timeout
    
    @abstractmethod
    def probe(self, target: str, **kwargs) -> ProbeResult:
        """Execute probe against target."""
        pass
    
    @property
    @abstractmethod
    def probe_type(self) -> ProbeType:
        pass


class TCPProbe(BaseProbe):
    """TCP connection probe."""
    
    @property
    def probe_type(self) -> ProbeType:
        return ProbeType.TCP
    
    def probe(self, target: str, port: int = 443, **kwargs) -> ProbeResult:
        start = time.perf_counter()
        try:
            with socket.create_connection((target, port), timeout=self.timeout):
                latency = (time.perf_counter() - start) * 1000
                return ProbeResult(
                    probe_type=self.probe_type,
                    target=f"{target}:{port}",
                    success=True,
                    latency_ms=latency
                )
        except Exception as e:
            return ProbeResult(
                probe_type=self.probe_type,
                target=f"{target}:{port}",
                success=False,
                latency_ms=None,
                error=str(e)
            )


class UDPProbe(BaseProbe):
    """UDP probe (send/recv)."""
    
    @property
    def probe_type(self) -> ProbeType:
        return ProbeType.UDP
    
    def probe(self, target: str, port: int = 53, payload: bytes = b'\x00', **kwargs) -> ProbeResult:
        start = time.perf_counter()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(self.timeout)
            sock.sendto(payload, (target, port))
            sock.recvfrom(1024)
            latency = (time.perf_counter() - start) * 1000
            return ProbeResult(
                probe_type=self.probe_type,
                target=f"{target}:{port}",
                success=True,
                latency_ms=latency
            )
        except Exception as e:
            return ProbeResult(
                probe_type=self.probe_type,
                target=f"{target}:{port}",
                success=False,
                latency_ms=None,
                error=str(e)
            )
        finally:
            try:
                sock.close()
            except:
                pass


class ICMPProbe(BaseProbe):
    """ICMP ping probe (requires root on Linux)."""
    
    @property
    def probe_type(self) -> ProbeType:
        return ProbeType.ICMP
    
    def probe(self, target: str, count: int = 3, **kwargs) -> ProbeResult:
        latencies = []
        errors = []
        
        for _ in range(count):
            start = time.perf_counter()
            try:
                # Use system ping command
                system = platform.system()
                if system == "Windows":
                    cmd = ["ping", "-n", "1", "-w", str(int(self.timeout * 1000)), target]
                else:
                    cmd = ["ping", "-c", "1", "-W", str(int(self.timeout)), target]
                
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout + 1)
                
                if result.returncode == 0:
                    # Parse latency from output
                    if system == "Windows":
                        match = re.search(r'time[<=](\d+)ms', result.stdout)
                    else:
                        match = re.search(r'time=(\d+\.?\d*)', result.stdout)
                    
                    if match:
                        latencies.append(float(match.group(1)))
                    else:
                        latencies.append((time.perf_counter() - start) * 1000)
                else:
                    errors.append("Ping failed")
            except Exception as e:
                errors.append(str(e))
        
        if latencies:
            return ProbeResult(
                probe_type=self.probe_type,
                target=target,
                success=True,
                latency_ms=sum(latencies) / len(latencies),
                metadata={'count': len(latencies), 'min': min(latencies), 'max': max(latencies)}
            )
        else:
            return ProbeResult(
                probe_type=self.probe_type,
                target=target,
                success=False,
                latency_ms=None,
                error='; '.join(errors) if errors else "All pings failed"
            )


class DNSProbe(BaseProbe):
    """Standard DNS query probe."""
    
    @property
    def probe_type(self) -> ProbeType:
        return ProbeType.DNS
    
    def __init__(self, timeout: float = 5.0, resolver_ip: Optional[str] = None):
        super().__init__(timeout)
        if not HAS_DNS:
            raise ImportError("dnspython is required for DNS probe. Install with: pip install dnspython")
        self.resolver = dns.resolver.Resolver()
        self.resolver.timeout = timeout
        self.resolver.lifetime = timeout
        if resolver_ip:
            self.resolver.nameservers = [resolver_ip]
    
    def probe(self, target: str, record_type: str = 'A', **kwargs) -> ProbeResult:
        start = time.perf_counter()
        try:
            answers = self.resolver.resolve(target, record_type)
            latency = (time.perf_counter() - start) * 1000
            return ProbeResult(
                probe_type=self.probe_type,
                target=f"{target} ({record_type})",
                success=True,
                latency_ms=latency,
                metadata={'records': [str(r) for r in answers], 'record_type': record_type}
            )
        except Exception as e:
            return ProbeResult(
                probe_type=self.probe_type,
                target=f"{target} ({record_type})",
                success=False,
                latency_ms=None,
                error=str(e)
            )


class DOHProbe(BaseProbe):
    """DNS over HTTPS probe."""
    
    @property
    def probe_type(self) -> ProbeType:
        return ProbeType.DOH
    
    def __init__(self, timeout: float = 5.0, doh_url: str = "https://cloudflare-dns.com/dns-query"):
        super().__init__(timeout)
        if not HAS_DNS:
            raise ImportError("dnspython is required for DoH probe. Install with: pip install dnspython")
        self.doh_url = doh_url
    
    def probe(self, target: str, record_type: str = 'A', **kwargs) -> ProbeResult:
        import urllib.request
        import urllib.parse
        import base64
        
        start = time.perf_counter()
        try:
            # Build DNS query
            query = dns.message.make_query(target, record_type)
            wire = query.to_wire()
            b64 = base64.urlsafe_b64encode(wire).decode().rstrip('=')
            
            url = f"{self.doh_url}?dns={b64}"
            req = urllib.request.Request(
                url,
                headers={'Accept': 'application/dns-message'}
            )
            
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                wire_response = response.read()
            
            latency = (time.perf_counter() - start) * 1000
            response_msg = dns.message.from_wire(wire_response)
            
            return ProbeResult(
                probe_type=self.probe_type,
                target=f"{target} ({record_type}) via DoH",
                success=True,
                latency_ms=latency,
                metadata={
                    'records': [str(r) for r in response_msg.answer],
                    'rcode': response_msg.rcode()
                }
            )
        except Exception as e:
            return ProbeResult(
                probe_type=self.probe_type,
                target=f"{target} ({record_type}) via DoH",
                success=False,
                latency_ms=None,
                error=str(e)
            )


class DOTProbe(BaseProbe):
    """DNS over TLS probe."""
    
    @property
    def probe_type(self) -> ProbeType:
        return ProbeType.DOT
    
    def __init__(self, timeout: float = 5.0, dot_host: str = "1.1.1.1", dot_port: int = 853):
        super().__init__(timeout)
        if not HAS_DNS:
            raise ImportError("dnspython is required for DoT probe. Install with: pip install dnspython")
        self.dot_host = dot_host
        self.dot_port = dot_port
    
    def probe(self, target: str, record_type: str = 'A', **kwargs) -> ProbeResult:
        start = time.perf_counter()
        try:
            # Create DNS query
            query = dns.message.make_query(target, record_type)
            
            # Connect via TLS
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            
            with socket.create_connection((self.dot_host, self.dot_port), timeout=self.timeout) as sock:
                with context.wrap_socket(sock, server_hostname=self.dot_host) as tls_sock:
                    # Send query length + query
                    wire = query.to_wire()
                    tls_sock.sendall(len(wire).to_bytes(2, 'big') + wire)
                    
                    # Read response length + response
                    length_bytes = tls_sock.recv(2)
                    if len(length_bytes) < 2:
                        raise Exception("Incomplete response length")
                    resp_len = int.from_bytes(length_bytes, 'big')
                    resp_wire = b''
                    while len(resp_wire) < resp_len:
                        chunk = tls_sock.recv(resp_len - len(resp_wire))
                        if not chunk:
                            break
                        resp_wire += chunk
            
            latency = (time.perf_counter() - start) * 1000
            response_msg = dns.message.from_wire(resp_wire)
            
            return ProbeResult(
                probe_type=self.probe_type,
                target=f"{target} ({record_type}) via DoT",
                success=True,
                latency_ms=latency,
                metadata={
                    'records': [str(r) for r in response_msg.answer],
                    'rcode': response_msg.rcode()
                }
            )
        except Exception as e:
            return ProbeResult(
                probe_type=self.probe_type,
                target=f"{target} ({record_type}) via DoT",
                success=False,
                latency_ms=None,
                error=str(e)
            )


class HTTPProbe(BaseProbe):
    """HTTP/HTTPS probe with full response analysis."""
    
    @property
    def probe_type(self) -> ProbeType:
        return ProbeType.HTTP
    
    def __init__(self, timeout: float = 10.0, follow_redirects: bool = True):
        super().__init__(timeout)
        self.follow_redirects = follow_redirects
    
    def probe(self, target: str, method: str = 'GET', 
              headers: Optional[Dict[str, str]] = None,
              expected_status: Optional[int] = None,
              **kwargs) -> ProbeResult:
        import urllib.request
        import urllib.error
        
        start = time.perf_counter()
        try:
            req = urllib.request.Request(target, method=method)
            if headers:
                for k, v in headers.items():
                    req.add_header(k, v)
            
            # Add User-Agent
            req.add_header('User-Agent', 'im/1.0 (Internet Monitor)')
            
            if self.follow_redirects:
                opener = urllib.request.build_opener()
            else:
                class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
                    def http_error_302(self, req, fp, code, msg, headers):
                        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)
                    def http_error_301(self, req, fp, code, msg, headers):
                        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)
                opener = urllib.request.build_opener(NoRedirectHandler())
            
            with opener.open(req, timeout=self.timeout) as response:
                latency = (time.perf_counter() - start) * 1000
                body = response.read()
                
                status = response.status
                success = True
                if expected_status and status != expected_status:
                    success = False
                
                return ProbeResult(
                    probe_type=self.probe_type,
                    target=target,
                    success=success,
                    latency_ms=latency,
                    metadata={
                        'status_code': status,
                        'headers': dict(response.headers),
                        'content_length': len(body),
                        'final_url': response.geturl()
                    }
                )
        except urllib.error.HTTPError as e:
            latency = (time.perf_counter() - start) * 1000
            return ProbeResult(
                probe_type=self.probe_type,
                target=target,
                success=False,
                latency_ms=latency,
                error=f"HTTP {e.code}: {e.reason}",
                metadata={'status_code': e.code}
            )
        except Exception as e:
            return ProbeResult(
                probe_type=self.probe_type,
                target=target,
                success=False,
                latency_ms=None,
                error=str(e)
            )


class TLSProbe(BaseProbe):
    """TLS certificate probe."""
    
    @property
    def probe_type(self) -> ProbeType:
        return ProbeType.TLS
    
    def probe(self, target: str, port: int = 443, **kwargs) -> ProbeResult:
        start = time.perf_counter()
        try:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            
            with socket.create_connection((target, port), timeout=self.timeout) as sock:
                with context.wrap_socket(sock, server_hostname=target) as tls_sock:
                    cert = tls_sock.getpeercert()
                    cipher = tls_sock.cipher()
                    version = tls_sock.version()
            
            latency = (time.perf_counter() - start) * 1000
            
            # Parse certificate details
            cert_info = {}
            if cert:
                cert_info = {
                    'subject': dict(x[0] for x in cert.get('subject', [])),
                    'issuer': dict(x[0] for x in cert.get('issuer', [])),
                    'version': cert.get('version'),
                    'serial_number': cert.get('serialNumber'),
                    'not_before': cert.get('notBefore'),
                    'not_after': cert.get('notAfter'),
                    'san': cert.get('subjectAltName', []),
                }
                
                # Check expiration
                import datetime
                not_after = cert.get('notAfter')
                if not_after:
                    exp_date = datetime.datetime.strptime(not_after, '%b %d %H:%M:%S %Y %Z')
                    days_left = (exp_date - datetime.datetime.utcnow()).days
                    cert_info['days_until_expiry'] = days_left
            
            return ProbeResult(
                probe_type=self.probe_type,
                target=f"{target}:{port}",
                success=True,
                latency_ms=latency,
                metadata={
                    'cipher': cipher,
                    'tls_version': version,
                    'certificate': cert_info
                }
            )
        except Exception as e:
            return ProbeResult(
                probe_type=self.probe_type,
                target=f"{target}:{port}",
                success=False,
                latency_ms=None,
                error=str(e)
            )


class ProbeManager:
    """Manages and executes probes."""
    
    def __init__(self, default_timeout: float = 5.0):
        self.default_timeout = default_timeout
        self.probes: Dict[ProbeType, BaseProbe] = {}
        self._register_default_probes()
    
    def _register_default_probes(self):
        self.register_probe(TCPProbe(self.default_timeout))
        self.register_probe(UDPProbe(self.default_timeout))
        # ICMP requires root, register but mark as requiring root
        self.register_probe(ICMPProbe(self.default_timeout))
        # Optional probes that may require additional dependencies
        try:
            self.register_probe(DNSProbe(self.default_timeout))
        except ImportError:
            pass
        try:
            self.register_probe(HTTPProbe(10.0))
        except ImportError:
            pass
        try:
            self.register_probe(TLSProbe(self.default_timeout))
        except ImportError:
            pass
        try:
            self.register_probe(DOHProbe(self.default_timeout))
        except ImportError:
            pass
        try:
            self.register_probe(DOTProbe(self.default_timeout))
        except ImportError:
            pass
    
    def register_probe(self, probe: BaseProbe):
        self.probes[probe.probe_type] = probe
    
    def get_probe(self, probe_type: ProbeType) -> Optional[BaseProbe]:
        return self.probes.get(probe_type)
    
    def run_probe(self, probe_type: ProbeType, target: str, **kwargs) -> ProbeResult:
        probe = self.probes.get(probe_type)
        if not probe:
            return ProbeResult(
                probe_type=probe_type,
                target=target,
                success=False,
                latency_ms=None,
                error=f"Probe type {probe_type.value} not registered"
            )
        return probe.probe(target, **kwargs)
    
    def run_all(self, target: str, probe_types: Optional[List[ProbeType]] = None, 
                **kwargs) -> Dict[ProbeType, ProbeResult]:
        if probe_types is None:
            probe_types = [p for p in self.probes.keys() if p != ProbeType.ICMP]  # Skip ICMP by default
        
        results = {}
        with ThreadPoolExecutor(max_workers=len(probe_types)) as executor:
            futures: Dict[Future, ProbeType] = {}
            for pt in probe_types:
                if pt in self.probes:
                    futures[executor.submit(self.run_probe, pt, target, **kwargs)] = pt
            
            for future in futures:
                pt = futures[future]
                try:
                    results[pt] = future.result(timeout=self.default_timeout + 2)
                except Exception as e:
                    results[pt] = ProbeResult(
                        probe_type=pt,
                        target=target,
                        success=False,
                        latency_ms=None,
                        error=str(e)
                    )
        return results
    
    def run_probe_set(self, target: str, probe_set: str = 'default', **kwargs) -> Dict[ProbeType, ProbeResult]:
        """Run a predefined set of probes."""
        sets = {
            'default': [ProbeType.TCP, ProbeType.DNS, ProbeType.HTTP],
            'comprehensive': [ProbeType.TCP, ProbeType.UDP, ProbeType.DNS, ProbeType.HTTP, ProbeType.TLS],
            'dns_only': [ProbeType.DNS, ProbeType.DOH, ProbeType.DOT],
            'connectivity': [ProbeType.TCP, ProbeType.ICMP, ProbeType.DNS],
            'tls': [ProbeType.TCP, ProbeType.TLS, ProbeType.HTTP],
        }
        probe_types = sets.get(probe_type, sets['default'])
        return self.run_all(target, probe_types, **kwargs)


# Global instance
_probe_manager: Optional[ProbeManager] = None


def get_probe_manager() -> ProbeManager:
    global _probe_manager
    if _probe_manager is None:
        _probe_manager = ProbeManager()
    return _probe_manager