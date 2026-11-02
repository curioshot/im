"""Install command - install dependencies."""

import typer
from rich.console import Console

from im.installer import get_installer
from im.cli.pipeline import PipelineRenderer


app = typer.Typer(name="install", help="Install/check dependencies for current platform")


@app.callback(invoke_without_command=True)
def install(
    check_only: bool = typer.Option(False, "--check", "-c", help="Only check, don't install"),
    no_install: bool = typer.Option(False, "--no-install", help="Fail if dependencies missing"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Install or check dependencies."""
    console = Console()
    installer = get_installer()

    if check_only:
        deps = installer.check_dependencies()
        _print_deps_table(console, deps, "Dependency Check")
        missing = [d for d in deps if d.status.value == "missing"]
        if missing:
            console.print(f"\n[red]Missing {len(missing)} dependencies[/red]")
            raise typer.Exit(1)
        else:
            console.print("\n[green]All dependencies satisfied[/green]")
        return

    # Run full pipeline
    renderer = PipelineRenderer(console)
    success = renderer.run_pipeline(installer, no_install=no_install)

    if not success and no_install:
        raise typer.Exit(1)


def _print_deps_table(console: Console, deps, title: str):
    """Print dependency table."""
    from rich.table import Table
    from im.installer.base import DepType, DepStatus

    table = Table(title=title, show_header=True, header_style="bold")
    table.add_column("Package", style="white")
    table.add_column("Type", style="grey62")
    table.add_column("Status", justify="center")
    table.add_column("Description", style="grey62")
    table.add_column("Required", justify="center")

    status_colors = {
        DepStatus.OK: "green",
        DepStatus.MISSING: "red",
        DepStatus.WILL_INSTALL: "yellow",
        DepStatus.INSTALLING: "blue",
        DepStatus.INSTALLED: "green",
        DepStatus.FAILED: "red",
        DepStatus.SKIPPED: "grey62",
    }

    for dep in deps:
        status_text = f"[{status_colors.get(dep.status, 'white')}]{dep.status.value}[/]"
        dep_type = "Python" if dep.dep_type == DepType.PYTHON else "System"
        required = "Yes" if dep.required else "No"
        table.add_row(dep.name, dep_type, status_text, dep.description, required)

    console.print(table)


if __name__ == "__main__":
    app()