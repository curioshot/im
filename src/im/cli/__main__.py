"""Main CLI entry point for im."""

import sys
import time
import typer
from rich.console import Console

from im.cli.commands import run_app, install_app, doctor_app, config_app, update_app
from im.cli.pipeline import PipelineRenderer
from im.installer import get_installer
from im.core.config import config


app = typer.Typer(
    name="im",
    help="Internet Monitor - Cross-platform connectivity TUI",
    add_completion=False,
    no_args_is_help=False,
    invoke_without_command=True,
)


# Add subcommands
app.add_typer(run_app, name="run")
app.add_typer(install_app, name="install")
app.add_typer(doctor_app, name="doctor")
app.add_typer(config_app, name="config")
app.add_typer(update_app, name="update")


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-v", help="Show version and exit"),
    no_install: bool = typer.Option(False, "--no-install", help="Skip auto-install, fail if deps missing"),
    verbose: bool = typer.Option(False, "--verbose", help="Verbose output"),
):
    """Internet Monitor - Cross-platform connectivity TUI."""
    if version:
        console = Console()
        console.print("im v1.0.0 - Internet Monitor")
        raise typer.Exit()

    # If no subcommand provided, run the monitor with auto-install
    if ctx.invoked_subcommand is None:
        _run_with_auto_install(no_install)


def _run_with_auto_install(no_install: bool):
    """Run monitor with automatic dependency installation."""
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

    # Import and run the monitor
    from im.cli.commands.run import run as run_cmd
    from typer.main import get_command

    # Create a new context for the run command
    run_cmd(
        typer.Context(get_command(run_app)),
        interval=config.get("interval", 1.0),
        timeout=config.get("timeout", 1.5),
        duration=config.get("duration", 0),
        no_speed=config.get("no_speed", False),
        root=config.get("root", False),
        no_install=True,  # Already checked
    )


if __name__ == "__main__":
    app()