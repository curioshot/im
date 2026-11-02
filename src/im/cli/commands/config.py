"""Config command - manage persistent configuration."""

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from im.core.config import config


app = typer.Typer(name="config", help="Manage persistent configuration")


@app.callback(invoke_without_command=True)
def config_cmd(
    show: bool = typer.Option(False, "--show", "-s", help="Show current configuration"),
    reset: bool = typer.Option(False, "--reset", help="Reset to defaults"),
    set_key: str = typer.Option(None, "--set", help="Set a config value (key=value)"),
    get_key: str = typer.Option(None, "--get", help="Get a config value"),
):
    """Manage configuration."""
    console = Console()

    if show or (not reset and not set_key and not get_key):
        _show_config(console)
    elif reset:
        _reset_config(console)
    elif set_key:
        _set_config(console, set_key)
    elif get_key:
        _get_config(console, get_key)


def _show_config(console: Console):
    """Display current configuration."""
    cfg = config.all()

    table = Table(title="⚙️  Configuration", show_header=True)
    table.add_column("Key", style="white")
    table.add_column("Value", style="cyan")
    table.add_column("Description", style="grey62")

    descriptions = {
        "interval": "Check interval in seconds",
        "timeout": "Probe timeout in seconds",
        "duration": "Stop after N seconds (0 = forever)",
        "no_speed": "Disable speed test",
        "root": "Enable DNS browsing log",
        "theme": "UI theme",
    }

    for key, value in cfg.items():
        desc = descriptions.get(key, "")
        table.add_row(key, str(value), desc)

    console.print(table)
    console.print(f"\nConfig file: {config.config_file}")


def _reset_config(console: Console):
    """Reset configuration to defaults."""
    config.reset()
    console.print("[green]Configuration reset to defaults[/green]")


def _set_config(console: Console, key_value: str):
    """Set a configuration value."""
    if "=" not in key_value:
        console.print("[red]Error: Use format key=value[/red]")
        raise typer.Exit(1)

    key, value = key_value.split("=", 1)

    # Type conversion
    if key in ("interval", "timeout"):
        try:
            value = float(value)
        except ValueError:
            console.print(f"[red]Error: {key} must be a number[/red]")
            raise typer.Exit(1)
    elif key == "duration":
        try:
            value = int(value)
        except ValueError:
            console.print(f"[red]Error: {key} must be an integer[/red]")
            raise typer.Exit(1)
    elif key in ("no_speed", "root"):
        value = value.lower() in ("true", "1", "yes", "on")

    config.set(key, value)
    console.print(f"[green]Set {key} = {value}[/green]")


def _get_config(console: Console, key: str):
    """Get a configuration value."""
    value = config.get(key)
    if value is None:
        console.print(f"[red]Key '{key}' not found[/red]")
        raise typer.Exit(1)
    console.print(value)


if __name__ == "__main__":
    app()