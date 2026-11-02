"""Visual pipeline renderer for dependency installation."""

import time
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn
from rich.text import Text
from rich.table import Table
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from im.installer.base import Dependency, DepStatus, DepType


@dataclass
class PipelineStage:
    name: str
    icon: str
    items: List[Dependency]


class PipelineRenderer:
    """Renders the installation pipeline with visual progress."""

    def __init__(self, console: Console):
        self.console = console
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
            console=console,
            transient=True,
        )

    def render_header(self, version: str = "1.0.0") -> Panel:
        """Render the header panel."""
        import platform
        import sys

        system = platform.system().lower()
        if system == "linux":
            try:
                import distro
                distro_name = f"{distro.name()} {distro.version()}"
            except Exception:
                distro_name = "Linux"
        elif system == "darwin":
            import subprocess
            version_out = subprocess.run(
                ["sw_vers", "-productVersion"], capture_output=True, text=True
            )
            distro_name = f"macOS {version_out.stdout.strip()}"
        elif system == "windows":
            distro_name = f"Windows {platform.release()}"
        else:
            distro_name = system

        header = Text()
        header.append("🌐  ", style="bold cyan")
        header.append("im - Internet Monitor  ", style="bold white")
        header.append(f"v{version}", style="green")
        header.append(f"\n📦  Platform: {distro_name} ({platform.machine()})", style="grey62")
        header.append(f"\n🐍  Python: {sys.version.split()[0]}", style="grey62")

        return Panel(header, border_style="cyan", padding=(1, 2))

    def render_checking(self, deps: List[Dependency]) -> Table:
        """Render dependency check table."""
        table = Table(title="🔍 Checking Dependencies", show_header=True, header_style="bold")
        table.add_column("Package", style="white")
        table.add_column("Type", style="grey62")
        table.add_column("Status", justify="center")
        table.add_column("Description", style="grey62")

        for dep in deps:
            status_text = self._format_status(dep.status)
            dep_type = "Python" if dep.dep_type == DepType.PYTHON else "System"
            table.add_row(dep.name, dep_type, status_text, dep.description)

        return table

    def _format_status(self, status: DepStatus) -> Text:
        """Format dependency status with colors."""
        icons = {
            DepStatus.OK: ("✅", "green"),
            DepStatus.MISSING: ("❌", "red"),
            DepStatus.WILL_INSTALL: ("📥", "yellow"),
            DepStatus.INSTALLING: ("⏳", "blue"),
            DepStatus.INSTALLED: ("✅", "green"),
            DepStatus.FAILED: ("❌", "red"),
            DepStatus.SKIPPED: ("⏭️", "grey62"),
        }
        icon, color = icons.get(status, ("?", "white"))
        return Text(f"{icon} {status.value}", style=color)

    def render_installing(self, deps: List[Dependency]) -> Table:
        """Render installation progress table."""
        table = Table(title="📥 Installing Dependencies", show_header=True, header_style="bold")
        table.add_column("Package", style="white")
        table.add_column("Type", style="grey62")
        table.add_column("Progress", justify="center")
        table.add_column("Description", style="grey62")

        for dep in deps:
            progress_text = self._format_status(dep.status)
            dep_type = "Python" if dep.dep_type == DepType.PYTHON else "System"
            table.add_row(dep.name, dep_type, progress_text, dep.description)

        return table

    def render_summary(self, deps: List[Dependency], success: bool) -> Panel:
        """Render installation summary."""
        installed = sum(1 for d in deps if d.status == DepStatus.INSTALLED)
        failed = sum(1 for d in deps if d.status == DepStatus.FAILED)
        skipped = sum(1 for d in deps if d.status == DepStatus.SKIPPED)
        already = sum(1 for d in deps if d.status == DepStatus.OK)

        summary = Text()
        if success:
            summary.append("✅  All dependencies satisfied!\n", style="bold green")
        else:
            summary.append("⚠️  Some dependencies failed to install\n", style="bold yellow")

        summary.append(f"  ✅ Already installed: {already}\n", style="green")
        summary.append(f"  📥 Newly installed: {installed}\n", style="blue")
        if skipped:
            summary.append(f"  ⏭️ Skipped (optional): {skipped}\n", style="grey62")
        if failed:
            summary.append(f"  ❌ Failed: {failed}\n", style="red")

        return Panel(summary, border_style="green" if success else "yellow", padding=(1, 2))

    def run_pipeline(self, installer, no_install: bool = False) -> bool:
        """Run the full installation pipeline with visual feedback."""
        # Stage 1: Detect
        self.console.print(self.render_header())

        # Stage 2: Check
        with Live(self.render_checking([]), console=self.console, refresh_per_second=10) as live:
            deps = installer.check_dependencies()
            live.update(self.render_checking(deps))
            time.sleep(0.5)

        # Show what will be installed
        missing = [d for d in deps if d.status == DepStatus.MISSING]
        if not missing:
            self.console.print(self.render_summary(deps, True))
            return True

        if no_install:
            self.console.print("[red]Missing dependencies but --no-install specified[/red]")
            return False

        # Mark missing as will_install
        for d in missing:
            d.status = DepStatus.WILL_INSTALL

        # Stage 3: Install
        with Live(self.render_installing(deps), console=self.console, refresh_per_second=10) as live:
            for dep in missing:
                live.update(self.render_installing(deps))
                dep.status = DepStatus.INSTALLING
                live.update(self.render_installing(deps))

                success = installer.install_dependency(dep)
                if success:
                    dep.status = DepStatus.INSTALLED
                else:
                    dep.status = DepStatus.FAILED
                live.update(self.render_installing(deps))
                time.sleep(0.2)

        # Stage 4: Verify
        with Live(self.render_checking([]), console=self.console, refresh_per_second=10) as live:
            deps = installer.check_dependencies()
            live.update(self.render_checking(deps))
            time.sleep(0.5)

        # Stage 5: Summary
        success = all(d.status != DepStatus.FAILED for d in missing)
        self.console.print(self.render_summary(deps, success))

        return success