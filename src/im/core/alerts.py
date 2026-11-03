"""Alerting and notification system for im."""

import os
import smtplib
import json
import threading
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
from pathlib import Path
import subprocess
import platform


class AlertLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class AlertRule:
    """Configuration for an alert rule."""
    name: str
    enabled: bool = True
    # Conditions
    max_latency_ms: Optional[float] = None
    max_loss_percent: Optional[float] = None
    min_download_mbps: Optional[float] = None
    min_upload_mbps: Optional[float] = None
    on_state_change: bool = False  # Alert on up/down transitions
    # Throttling
    cooldown_seconds: int = 300  # 5 minutes default
    # Actions
    notify_desktop: bool = True
    notify_sound: bool = False
    notify_email: bool = False
    notify_webhook: bool = False
    webhook_url: str = ""
    email_recipients: List[str] = field(default_factory=list)
    # Custom
    custom_message: str = ""


@dataclass
class Alert:
    """An alert instance."""
    rule_name: str
    level: AlertLevel
    message: str
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)


class Notifier(ABC):
    """Base class for notification backends."""
    
    @abstractmethod
    def send(self, alert: Alert) -> bool:
        """Send alert. Return True on success."""
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Notifier name."""
        pass


class DesktopNotifier(Notifier):
    """Desktop notifications via libnotify/macOS/Windows."""
    
    @property
    def name(self) -> str:
        return "desktop"
    
    def send(self, alert: Alert) -> bool:
        system = platform.system()
        title = f"im Alert: {alert.rule_name}"
        message = alert.message
        
        try:
            if system == "Linux":
                # Use notify-send
                urgency = "critical" if alert.level == AlertLevel.CRITICAL else "normal"
                subprocess.run([
                    "notify-send", "-u", urgency, "-t", "5000",
                    title, message
                ], check=True, timeout=5)
                return True
            
            elif system == "Darwin":  # macOS
                # Use osascript
                script = f'display notification "{message}" with title "{title}"'
                subprocess.run(["osascript", "-e", script], check=True, timeout=5)
                return True
            
            elif system == "Windows":
                # Use PowerShell with BurntToast or simple toast
                ps_script = f'''
                [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
                $template = [Windows.UI.Notifications.ToastTemplateType]::ToastText02
                $xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($template)
                $text = $xml.GetElementsByTagName("text")
                $text[0].AppendChild($xml.CreateTextNode("{title}")) | Out-Null
                $text[1].AppendChild($xml.CreateTextNode("{message}")) | Out-Null
                $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
                [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("im").Show($toast)
                '''
                subprocess.run(["powershell", "-Command", ps_script], check=True, timeout=5)
                return True
                
        except Exception as e:
            print(f"Desktop notification failed: {e}")
            return False
        
        return False


class SoundNotifier(Notifier):
    """Sound alerts."""
    
    @property
    def name(self) -> str:
        return "sound"
    
    def __init__(self):
        self._sounds = {
            AlertLevel.INFO: None,
            AlertLevel.WARNING: None,
            AlertLevel.CRITICAL: None,
        }
        self._init_sounds()
    
    def _init_sounds(self):
        system = platform.system()
        if system == "Linux":
            # Try to find system sounds
            for level in AlertLevel:
                paths = [
                    f"/usr/share/sounds/freedesktop/stereo/{'dialog-warning' if level==AlertLevel.WARNING else 'dialog-information' if level==AlertLevel.INFO else 'alarm-clock-elapsed'}.oga",
                    f"/usr/share/sounds/ubuntu/stereo/{'dialog-warning' if level==AlertLevel.WARNING else 'message-new-instant' if level==AlertLevel.INFO else 'alarm-clock-elapsed'}.ogg",
                ]
                for p in paths:
                    if Path(p).exists():
                        self._sounds[level] = p
                        break
        elif system == "Darwin":
            # macOS system sounds
            self._sounds = {
                AlertLevel.INFO: "/System/Library/Sounds/Glass.aiff",
                AlertLevel.WARNING: "/System/Library/Sounds/Basso.aiff",
                AlertLevel.CRITICAL: "/System/Library/Sounds/Sosumi.aiff",
            }
        elif system == "Windows":
            # Windows system sounds
            self._sounds = {
                AlertLevel.INFO: "SystemAsterisk",
                AlertLevel.WARNING: "SystemExclamation",
                AlertLevel.CRITICAL: "SystemHand",
            }
    
    def send(self, alert: Alert) -> bool:
        sound_path = self._sounds.get(alert.level)
        if not sound_path:
            return False
        
        try:
            system = platform.system()
            if system == "Linux":
                subprocess.run(["paplay", sound_path], check=False, timeout=5)
            elif system == "Darwin":
                subprocess.run(["afplay", sound_path], check=False, timeout=5)
            elif system == "Windows":
                import winsound
                winsound.PlaySound(sound_path, winsound.SND_ALIAS | winsound.SND_ASYNC)
            return True
        except Exception as e:
            print(f"Sound notification failed: {e}")
            return False
        
        return False


class EmailNotifier(Notifier):
    """Email notifications via SMTP."""
    
    def __init__(self, smtp_host: str, smtp_port: int, username: str, password: str,
                 use_tls: bool = True, from_addr: Optional[str] = None):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.from_addr = from_addr or username
    
    @property
    def name(self) -> str:
        return "email"
    
    def send(self, alert: Alert) -> bool:
        # Get recipients from alert metadata
        recipients = alert.metadata.get('email_recipients', [])
        if not recipients:
            return False
        
        try:
            msg = MIMEMultipart()
            msg['From'] = self.from_addr
            msg['To'] = ', '.join(recipients)
            msg['Subject'] = f"[im Alert] {alert.rule_name} - {alert.level.value.upper()}"
            
            body = f"""
Alert: {alert.rule_name}
Level: {alert.level.value.upper()}
Time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(alert.timestamp))}
Message: {alert.message}

Metadata:
{json.dumps(alert.metadata, indent=2)}
"""
            msg.attach(MIMEText(body, 'plain'))
            
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                if self.use_tls:
                    server.starttls()
                server.login(self.username, self.password)
                server.send_message(msg)
            
            return True
        except Exception as e:
            print(f"Email notification failed: {e}")
            return False


class WebhookNotifier(Notifier):
    """Webhook notifications (Slack, Discord, generic)."""
    
    def __init__(self, webhook_url: str, template: Optional[str] = None):
        self.webhook_url = webhook_url
        self.template = template
    
    @property
    def name(self) -> str:
        return "webhook"
    
    def send(self, alert: Alert) -> bool:
        try:
            import urllib.request
            import urllib.parse
            
            if self.template:
                # Use custom template
                payload = json.loads(self.template.format(
                    title=alert.rule_name,
                    level=alert.level.value,
                    message=alert.message,
                    timestamp=time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(alert.timestamp)),
                    **alert.metadata
                ))
            else:
                # Default payload format (works for Slack/Discord)
                color = {
                    AlertLevel.INFO: 0x00ff00,
                    AlertLevel.WARNING: 0xffaa00,
                    AlertLevel.CRITICAL: 0xff0000,
                }.get(alert.level, 0x808080)
                
                payload = {
                    "embeds": [{
                        "title": f"im Alert: {alert.rule_name}",
                        "description": alert.message,
                        "color": color,
                        "timestamp": datetime.fromtimestamp(alert.timestamp).isoformat(),
                        "fields": [
                            {"name": "Level", "value": alert.level.value.upper(), "inline": True},
                            {"name": "Rule", "value": alert.rule_name, "inline": True},
                        ]
                    }]
                }
            
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                self.webhook_url,
                data=data,
                headers={'Content-Type': 'application/json'}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status == 200
        except Exception as e:
            print(f"Webhook notification failed: {e}")
            return False


class AlertManager:
    """Manages alert rules and dispatches notifications."""
    
    def __init__(self, config_dir: Optional[Path] = None):
        if config_dir is None:
            if os.name == 'nt':
                base = Path(os.environ.get('LOCALAPPDATA', Path.home()))
            else:
                base = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
            config_dir = base / 'im'
        
        self.config_dir = config_dir
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.rules_file = config_dir / 'alerts.json'
        
        self.rules: Dict[str, AlertRule] = {}
        self.notifiers: Dict[str, Notifier] = {}
        self._last_alert: Dict[str, float] = {}  # rule_name -> last_alert_time
        self._lock = threading.Lock()
        
        # Register default notifiers
        self._register_default_notifiers()
        
        # Load rules
        self.load_rules()
        
        # Start evaluation thread
        self._stop_eval = threading.Event()
        self._eval_thread = threading.Thread(target=self._eval_loop, daemon=True)
        self._eval_thread.start()
    
    def _register_default_notifiers(self):
        """Register default notifiers."""
        self.notifiers['desktop'] = DesktopNotifier()
        self.notifiers['sound'] = SoundNotifier()
        # Email and webhook need config, add via register_notifier
    
    def register_notifier(self, name: str, notifier: Notifier):
        """Register a custom notifier."""
        self.notifiers[name] = notifier
    
    def configure_email(self, smtp_host: str, smtp_port: int, username: str,
                        password: str, use_tls: bool = True, from_addr: Optional[str] = None):
        """Configure email notifier."""
        self.notifiers['email'] = EmailNotifier(smtp_host, smtp_port, username, password, use_tls)
    
    def configure_webhook(self, name: str, webhook_url: str, template: Optional[str] = None):
        """Configure a webhook notifier."""
        self.notifiers[name] = WebhookNotifier(webhook_url, template)
    
    def load_rules(self):
        """Load alert rules from config file."""
        if self.rules_file.exists():
            try:
                with open(self.rules_file) as f:
                    data = json.load(f)
                    for rule_data in data.get('rules', []):
                        rule = AlertRule(**rule_data)
                        self.rules[rule.name] = rule
            except Exception as e:
                print(f"Failed to load alert rules: {e}")
    
    def save_rules(self):
        """Save alert rules to config file."""
        try:
            data = {'rules': [self._rule_to_dict(r) for r in self.rules.values()]}
            with open(self.rules_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Failed to save alert rules: {e}")
    
    def _rule_to_dict(self, rule: AlertRule) -> dict:
        return {
            'name': rule.name,
            'enabled': rule.enabled,
            'max_latency_ms': rule.max_latency_ms,
            'max_loss_percent': rule.max_loss_percent,
            'min_download_mbps': rule.min_download_mbps,
            'min_upload_mbps': rule.min_upload_mbps,
            'on_state_change': rule.on_state_change,
            'cooldown_seconds': rule.cooldown_seconds,
            'notify_desktop': rule.notify_desktop,
            'notify_sound': rule.notify_sound,
            'notify_email': rule.notify_email,
            'notify_webhook': rule.notify_webhook,
            'webhook_url': rule.webhook_url,
            'email_recipients': rule.email_recipients,
            'custom_message': rule.custom_message,
        }
    
    def add_rule(self, rule: AlertRule):
        """Add or update an alert rule."""
        with self._lock:
            self.rules[rule.name] = rule
            self.save_rules()
    
    def remove_rule(self, name: str):
        """Remove an alert rule."""
        with self._lock:
            if name in self.rules:
                del self.rules[name]
                self.save_rules()
    
    def get_rule(self, name: str) -> Optional[AlertRule]:
        return self.rules.get(name)
    
    def list_rules(self) -> List[AlertRule]:
        return list(self.rules.values())
    
    def evaluate(self, metrics: Dict[str, Any], state_change: Optional[str] = None):
        """Evaluate all rules against current metrics."""
        with self._lock:
            for rule in self.rules.values():
                if not rule.enabled:
                    continue
                
                # Check cooldown
                last = self._last_alert.get(rule.name, 0)
                if time.time() - last < rule.cooldown_seconds:
                    continue
                
                triggered = False
                level = AlertLevel.INFO
                message = rule.custom_message or ""
                
                # Check conditions
                if rule.max_latency_ms and metrics.get('avg_latency_ms', 0) > rule.max_latency_ms:
                    triggered = True
                    level = AlertLevel.WARNING
                    message = f"Latency {metrics.get('avg_latency_ms', 0):.0f}ms exceeds {rule.max_latency_ms}ms"
                
                if rule.max_loss_percent and metrics.get('loss_percent', 0) > rule.max_loss_percent:
                    triggered = True
                    level = AlertLevel.CRITICAL
                    message = f"Packet loss {metrics.get('loss_percent', 0):.1f}% exceeds {rule.max_loss_percent}%"
                
                if rule.min_download_mbps and metrics.get('download_mbps', 0) < rule.min_download_mbps:
                    triggered = True
                    level = AlertLevel.WARNING
                    message = f"Download {metrics.get('download_mbps', 0):.1f}Mbps below {rule.min_download_mbps}Mbps"
                
                if rule.min_upload_mbps and metrics.get('upload_mbps', 0) < rule.min_upload_mbps:
                    triggered = True
                    level = AlertLevel.WARNING
                    message = f"Upload {metrics.get('upload_mbps', 0):.1f}Mbps below {rule.min_upload_mbps}Mbps"
                
                if rule.on_state_change and state_change:
                    triggered = True
                    level = AlertLevel.CRITICAL if state_change == 'down' else AlertLevel.INFO
                    message = f"Connection {state_change}"
                
                if triggered:
                    self._fire_alert(rule, level, message, {
                        'latency_ms': metrics.get('avg_latency_ms'),
                        'loss_percent': metrics.get('loss_percent'),
                        'download_mbps': metrics.get('download_mbps'),
                        'upload_mbps': metrics.get('upload_mbps'),
                        'state_change': state_change,
                    })
    
    def _fire_alert(self, rule: AlertRule, level: AlertLevel, message: str, metadata: Dict):
        """Fire an alert through configured notifiers."""
        alert = Alert(
            rule_name=rule.name,
            level=level,
            message=message,
            timestamp=time.time(),
            metadata=metadata
        )
        
        # Add rule-specific metadata
        alert.metadata['email_recipients'] = rule.email_recipients
        alert.metadata['webhook_url'] = rule.webhook_url
        
        # Send through enabled notifiers
        sent = False
        if rule.notify_desktop and 'desktop' in self.notifiers:
            if self.notifiers['desktop'].send(Alert(rule.name, level, message, time.time(), metadata)):
                sent = True
        
        if rule.notify_sound and 'sound' in self.notifiers:
            if self.notifiers['sound'].send(Alert(rule.name, level, message, time.time(), metadata)):
                sent = True
        
        if rule.notify_email and 'email' in self.notifiers:
            alert.metadata['email_recipients'] = rule.email_recipients
            if self.notifiers['email'].send(alert):
                sent = True
        
        if rule.notify_webhook and 'webhook' in self.notifiers:
            alert.metadata['webhook_url'] = rule.webhook_url
            if self.notifiers['webhook'].send(alert):
                sent = True
        
        if sent:
            self._last_alert[rule.name] = time.time()
    
    def test_alert(self, rule_name: str) -> bool:
        """Test an alert rule by firing a test alert."""
        rule = self.rules.get(rule_name)
        if not rule:
            return False
        
        self._fire_alert(rule, AlertLevel.INFO, f"Test alert for {rule_name}", {'test': True})
        return True
    
    def _eval_loop(self):
        """Background evaluation loop."""
        while not self._stop_eval.is_set():
            time.sleep(10)  # Evaluate every 10 seconds
    
    def stop(self):
        """Stop evaluation thread."""
        self._stop_eval.set()
        if self._eval_thread:
            self._eval_thread.join(timeout=5.0)


# Global instance
_alert_manager: Optional[AlertManager] = None


def get_alert_manager() -> AlertManager:
    """Get global alert manager instance."""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager()
    return _alert_manager