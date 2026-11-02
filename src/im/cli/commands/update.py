"""Update command - self-update."""

import typer
import subprocess
import sys
from rich.console import Console


app = typer.Typer(name="update", help="Update im to latest version")


@app.callback(invoke_without_command=True)
def update(
    check_only: bool = typer.Option(False, "--check", "-c", help="Only check for updates"),
    force: bool = typer.Option(False, "--force", "-f", help="Force update even if up to date"),
):
    """Update im."""
    console = Console()

    # Check if installed via pipx
    try:
        result = subprocess.run(
            ["pipx", "list", "--short"], capture_output=True, text=True
        )
        if "im" in result.stdout:
            if check_only:
                console.print("Checking for updates via pipx...")
                result = subprocess.run(["pipx", "upgrade", "im", "--dry-run"], capture_output=True, text=True)
                if "would be upgraded" in result.stdout or "up to date" in result.stdout.lower():
                    console.print("[green]Already up to date[/green]")
                else:
                    console.print("[yellow]Update available[/yellow]")
                return

            console.print("Updating via pipx...")
            result = subprocess.run(["pipx", "upgrade", "im"], capture_output=True, text=True)
            if result.returncode == 0:
                console.print("[green]Updated successfully![/green]")
            else:
                console.print(f"[red]Update failed: {result.stderr}[/red]")
                raise typer.Exit(1)
            return
    except FileNotFoundError:
        pass

    # Check if installed via pip
    try:
        import im
        current_version = im.__version__
    except Exception:
        current_version = "unknown"

    if check_only:
        console.print(f"Current version: {current_version}")
        console.print("Check GitHub releases for updates: https://github.com/user/im/releases")
        return

    # Try pip install --upgrade
    console.print("Updating via pip...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "im"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        console.print("[green]Updated successfully![/green]")
    else:
        console.print(f"[red]Update failed: {result.stderr}[/red]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()