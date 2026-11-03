"""Alerts command - manage alert rules and notifications."""

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Prompt, Confirm
from typing import Optional, List
import json

from ...core.alerts import get_alert_manager, AlertRule, AlertLevel
from ...core.config import config


app = typer.Typer(name="alerts", help="Manage alert rules and notifications")


@app.command("list")
def list_rules(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """List all alert rules."""
    console = Console()
    am = get_alert_manager()
    
    rules = am.list_rules()
    
    if json_output:
        console.print_json(json.dumps([{
            'name': r.name,
            'enabled': r.enabled,
            'max_latency_ms': r.max_latency_ms,
            'max_loss_percent': r.max_loss_percent,
            'min_download_mbps': r.min_download_mbps,
            'min_upload_mbps': r.min_upload_mbps,
            'on_state_change': r.on_state_change,
            'cooldown_seconds': r.cooldown_seconds,
            'notify_desktop': r.notify_desktop,
            'notify_sound': r.notify_sound,
            'notify_email': r.notify_email,
            'notify_webhook': r.notify_webhook,
        } for r in rules]))
        return
    
    if not rules:
        console.print("[yellow]No alert rules configured[/yellow]")
        console.print("Use 'im alerts add' to create one")
        return
    
    table = Table(title="Alert Rules", show_header=True)
    table.add_column("Name", style="cyan")
    table.add_column("Enabled", justify="center")
    table.add_column("Conditions")
    table.add_column("Cooldown")
    table.add_column("Actions")
    
    for r in rules:
        conditions = []
        if r.max_latency_ms:
            conditions.append(f"latency > {r.max_latency_ms}ms")
        if r.max_loss_percent:
            conditions.append(f"loss > {r.max_loss_percent}%")
        if r.min_download_mbps:
            conditions.append(f"download < {r.min_download_mbps}Mbps")
        if r.min_upload_mbps:
            conditions.append(f"upload < {r.min_upload_mbps}Mbps")
        if r.on_state_change:
            conditions.append("state change")
        
        actions = []
        if r.notify_desktop:
            actions.append("🖥️")
        if r.notify_sound:
            actions.append("🔊")
        if r.notify_email:
            actions.append("📧")
        if r.notify_webhook:
            actions.append("🔗")
        
        enabled = "✅" if r.enabled else "❌"
        
        table.add_row(
            r.name,
            enabled,
            "\n".join(conditions) or "none",
            f"{r.cooldown_seconds}s",
            " ".join(actions) or "none"
        )
    
    console.print(table)


@app.command("add")
def add_rule(
    name: str = typer.Argument(..., help="Rule name"),
    enabled: bool = typer.Option(True, "--enabled/--disabled", help="Enable rule"),
    max_latency: Optional[float] = typer.Option(None, "--max-latency", help="Max latency (ms)"),
    max_loss: Optional[float] = typer.Option(None, "--max-loss", help="Max packet loss (%)"),
    min_download: Optional[float] = typer.Option(None, "--min-download", help="Min download (Mbps)"),
    min_upload: Optional[float] = typer.Option(None, "--min-upload", help="Min upload (Mbps)"),
    on_change: bool = typer.Option(False, "--on-change", help="Alert on state change"),
    cooldown: int = typer.Option(300, "--cooldown", help="Cooldown seconds"),
    desktop: bool = typer.Option(True, "--desktop/--no-desktop", help="Desktop notification"),
    sound: bool = typer.Option(False, "--sound/--no-sound", help="Sound alert"),
    email: bool = typer.Option(False, "--email/--no-email", help="Email notification"),
    webhook: bool = typer.Option(False, "--webhook/--no-webhook", help="Webhook notification"),
    webhook_url: str = typer.Option("", "--webhook-url", help="Webhook URL"),
    email_recipients: str = typer.Option("", "--email-to", help="Email recipients (comma-separated)"),
    message: str = typer.Option("", "--message", help="Custom message template"),
):
    """Add a new alert rule."""
    console = Console()
    am = get_alert_manager()
    
    if name in [r.name for r in am.list_rules()]:
        console.print(f"[red]Rule '{name}' already exists[/red]")
        raise typer.Exit(1)
    
    rule = AlertRule(
        name=name,
        enabled=enabled,
        max_latency_ms=max_latency,
        max_loss_percent=max_loss,
        min_download_mbps=min_download,
        min_upload_mbps=min_upload,
        on_state_change=on_change,
        cooldown_seconds=cooldown,
        notify_desktop=desktop,
        notify_sound=sound,
        notify_email=email,
        notify_webhook=webhook,
        webhook_url=webhook_url,
        email_recipients=[e.strip() for e in email_recipients.split(",") if e.strip()],
        custom_message=message,
    )
    
    am.add_rule(rule)
    console.print(f"[green]Added alert rule '{name}'[/green]")


@app.command("remove")
def remove_rule(
    name: str = typer.Argument(..., help="Rule name"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Remove an alert rule."""
    console = Console()
    am = get_alert_manager()
    
    if name not in [r.name for r in am.list_rules()]:
        console.print(f"[red]Rule '{name}' not found[/red]")
        raise typer.Exit(1)
    
    if not force:
        if not Confirm.ask(f"Remove rule '{name}'?"):
            return
    
    am.remove_rule(name)
    console.print(f"[green]Removed rule '{name}'[/green]")


@app.command("edit")
def edit_rule(
    name: str = typer.Argument(..., help="Rule name"),
    enabled: Optional[bool] = typer.Option(None, "--enabled/--disabled", help="Enable/disable rule"),
    max_latency: Optional[float] = typer.Option(None, "--max-latency", help="Max latency (ms)"),
    max_loss: Optional[float] = typer.Option(None, "--max-loss", help="Max packet loss (%)"),
    min_download: Optional[float] = typer.Option(None, "--min-download", help="Min download (Mbps)"),
    min_upload: Optional[float] = typer.Option(None, "--min-upload", help="Min upload (Mbps)"),
    on_change: Optional[bool] = typer.Option(None, "--on-change/--no-on-change", help="Alert on state change"),
    cooldown: Optional[int] = typer.Option(None, "--cooldown", help="Cooldown seconds"),
    desktop: Optional[bool] = typer.Option(None, "--desktop/--no-desktop", help="Desktop notification"),
    sound: Optional[bool] = typer.Option(None, "--sound/--no-sound", help="Sound alert"),
    email: Optional[bool] = typer.Option(None, "--email/--no-email", help="Email notification"),
    webhook: Optional[bool] = typer.Option(None, "--webhook/--no-webhook", help="Webhook notification"),
):
    """Edit an existing alert rule."""
    console = Console()
    am = get_alert_manager()
    
    rule = am.get_rule(name)
    if not rule:
        console.print(f"[red]Rule '{name}' not found[/red]")
        raise typer.Exit(1)
    
    # Update only provided values
    if enabled is not None:
        rule.enabled = enabled
    if max_latency is not None:
        rule.max_latency_ms = max_latency
    if max_loss is not None:
        rule.max_loss_percent = max_loss
    if min_download is not None:
        rule.min_download_mbps = min_download
    if min_upload is not None:
        rule.min_upload_mbps = min_upload
    if on_change is not None:
        rule.on_state_change = on_change
    if cooldown is not None:
        rule.cooldown_seconds = cooldown
    if desktop is not None:
        rule.notify_desktop = desktop
    if sound is not None:
        rule.notify_sound = sound
    if email is not None:
        rule.notify_email = email
    if webhook is not None:
        rule.notify_webhook = webhook
    
    am.add_rule(rule)  # This updates and saves
    console.print(f"[green]Updated rule '{name}'[/green]")


@app.command("test")
def test_alert(
    name: str = typer.Argument(..., help="Rule name to test"),
):
    """Test an alert rule by firing a test notification."""
    console = Console()
    am = get_alert_manager()
    
    if not am.test_alert(name):
        console.print(f"[red]Rule '{name}' not found or test failed[/red]")
        raise typer.Exit(1)
    
    console.print(f"[green]Test alert sent for rule '{name}'[/green]")


@app.command("config")
def config_notifiers(
    email_host: Optional[str] = typer.Option(None, "--email-host", help="SMTP host"),
    email_port: int = typer.Option(587, "--email-port", help="SMTP port"),
    email_user: Optional[str] = typer.Option(None, "--email-user", help="SMTP username"),
    email_pass: Optional[str] = typer.Option(None, "--email-pass", help="SMTP password"),
    email_tls: bool = typer.Option(True, "--email-tls/--no-email-tls", help="Use TLS"),
    webhook_name: Optional[str] = typer.Option(None, "--webhook-name", help="Webhook name"),
    webhook_url: Optional[str] = typer.Option(None, "--webhook-url", help="Webhook URL"),
    webhook_template: Optional[str] = typer.Option(None, "--webhook-template", help="Custom JSON template"),
):
    """Configure email and webhook notifiers."""
    console = Console()
    am = get_alert_manager()
    
    if email_host and email_user and email_pass:
        am.configure_email(email_host, email_port, email_user, email_pass)
        console.print("[green]Email notifier configured[/green]")
    
    if webhook_name and webhook_url:
        am.configure_webhook(webhook_name, webhook_url)
        console.print(f"[green]Webhook '{webhook_name}' configured[/green]")
    
    if not any([email_host, webhook_name]):
        console.print("[yellow]No configuration provided. Use --email-host or --webhook-name[/yellow]")


@app.command("show")
def show_rule(
    name: str = typer.Argument(..., help="Rule name"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show details of a specific rule."""
    console = Console()
    am = get_alert_manager()
    
    rule = am.get_rule(name)
    if not rule:
        console.print(f"[red]Rule '{name}' not found[/red]")
        raise typer.Exit(1)
    
    if json_output:
        from ...core.alerts import AlertRule
        console.print_json(json.dumps({
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
        }))
        return
    
    panel = Panel(
        f"""[bold]Name:[/bold] {rule.name}
[bold]Enabled:[/bold] {'Yes' if rule.enabled else 'No'}
[bold]Conditions:[/bold]
  Max Latency: {rule.max_latency_ms}ms
  Max Loss: {rule.max_loss_percent}%
  Min Download: {rule.min_download_mbps}Mbps
  Min Upload: {rule.min_upload_mbps}Mbps
  On State Change: {'Yes' if rule.on_state_change else 'No'}
[bold]Cooldown:[/bold] {rule.cooldown_seconds}s
[bold]Notifications:[/bold]
  Desktop: {'Yes' if rule.notify_desktop else 'No'}
  Sound: {'Yes' if rule.notify_sound else 'No'}
  Email: {'Yes' if rule.notify_email else 'No'}
  Webhook: {'Yes' if rule.notify_webhook else 'No'}
[bold]Webhook URL:[/bold] {rule.webhook_url or 'N/A'}
[bold]Email Recipients:[/bold] {', '.join(rule.email_recipients) or 'N/A'}
[bold]Custom Message:[/bold] {rule.custom_message or 'N/A'}""",
        title=f"Alert Rule: {rule.name}",
        border_style="blue"
    )
    console.print(panel)


@app.command("enable")
def enable_rule(
    name: str = typer.Argument(..., help="Rule name"),
):
    """Enable an alert rule."""
    console = Console()
    am = get_alert_manager()
    
    rule = am.get_rule(name)
    if not rule:
        console.print(f"[red]Rule '{name}' not found[/red]")
        raise typer.Exit(1)
    
    rule.enabled = True
    am.add_rule(rule)
    console.print(f"[green]Enabled rule '{name}'[/green]")


@app.command("disable")
def disable_rule(
    name: str = typer.Argument(..., help="Rule name"),
):
    """Disable an alert rule."""
    console = Console()
    am = get_alert_manager()
    
    rule = am.get_rule(name)
    if not rule:
        console.print(f"[red]Rule '{name}' not found[/red]")
        raise typer.Exit(1)
    
    rule.enabled = False
    am.add_rule(rule)
    console.print(f"[yellow]Disabled rule '{name}'[/yellow]")


if __name__ == "__main__":
    app()