"""Doctor command - system diagnostics."""

import sys
import platform
import subprocess
import shutil
import os
from typing import Dict, Any

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from im.platform import get_platform
from im.installer import get_installer


app = typer.Typer(name="doctor", help="Show system diagnostics and readiness")


@app.callback(invoke_without_command=True)
def doctor(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Run system diagnostics."""
    console = Console()
    pf = get_platform()
    installer = get_installer()

    # Collect all diagnostics
    diagnostics = {
        "platform": _get_platform_info(pf),
        "python": _get_python_info(),
        "dependencies": _get_dependency_info(installer),
        "capabilities": _get_capabilities(pf),
        "network": _get_network_info(pf),
    }

    if json_output:
        import json
        console.print_json(json.dumps(diagnostics, indent=2))
        return

    # Render pretty output
    _render_diagnostics(console, diagnostics, verbose)


def _get_platform_info(pf) -> Dict[str, Any]:
    info = pf.get_platform_info()
    return {
        "system": info.system,
        "distro": info.distro,
        "distro_version": info.distro_version,
        "arch": info.arch,
        "is_termux": info.is_termux,
        "is_wsl": info.is_wsl,
        "has_sudo": info.has_sudo,
        "has_admin": info.has_admin,
    }


def _get_python_info() -> Dict[str, Any]:
    return {
        "version": sys.version.split()[0],
        "executable": sys.executable,
        "prefix": sys.prefix,
        "path": sys.path[:3],
    }


def _get_dependency_info(installer) -> Dict[str, Any]:
    deps = installer.check_dependencies()
    return {
        "total": len(deps),
        "ok": sum(1 for d in deps if d.status.value == "ok"),
        "missing": sum(1 for d in deps if d.status.value == "missing"),
        "failed": sum(1 for d in deps if d.status.value == "failed"),
        "details": [
            {
                "name": d.name,
                "type": d.dep_type.value,
                "status": d.status.value,
                "required": d.required,
                "description": d.description,
            }
            for d in deps
        ],
    }


def _get_capabilities(pf) -> Dict[str, Any]:
    return {
        "default_gateway": pf.get_default_gateway(),
        "wifi_info": pf.get_wifi_info(),
        "admin_access": pf.check_admin(),
        "dns_sniffer_available": pf.create_dns_sniffer() is not None,
        "package_manager": pf.get_package_manager(),
    }


def _get_network_info(pf) -> Dict[str, Any]:
    return {
        "interfaces": list(pf.get_interface_counters().keys()),
        "arp_entries": len(pf.get_arp_table()),
    }


def _render_diagnostics(console: Console, diagnostics: Dict, verbose: bool):
    # Platform panel
    p = diagnostics["platform"]
    platform_text = Text()
    platform_text.append("Platform: ", style="bold")
    platform_text.append(f"{p['system']} ({p['distro']} {p['distro_version']})\n")
    platform_text.append("Architecture: ", style="bold")
    platform_text.append(f"{p['arch']}\n")
    if p['is_termux']:
        platform_text.append("Environment: ", style="bold")
        platform_text.append("Termux (Android)\n")
    if p['is_wsl']:
        platform_text.append("Environment: ", style="bold")
        platform_text.append("WSL\n")
    platform_text.append("Privileges: ", style="bold")
    if p['has_sudo']:
        platform_text.append("sudo ✓")
    elif p['has_admin']:
        platform_text.append("Admin ✓")
    else:
        platform_text.append("User (no sudo/admin)")

    console.print(Panel(platform_text, title="🖥️  Platform", border_style="cyan"))

    # Python panel
    py = diagnostics["python"]
    python_text = Text()
    python_text.append("Version: ", style="bold")
    python_text.append(f"{py['version']}\n")
    python_text.append("Executable: ", style="bold")
    python_text.append(f"{py['executable']}\n")
    python_text.append("Prefix: ", style="bold")
    python_text.append(f"{py['prefix']}")

    console.print(Panel(python_text, title="🐍  Python", border_style="green"))

    # Dependencies table
    deps = diagnostics["dependencies"]
    table = Table(title=f"📦 Dependencies ({deps['ok']}/{deps['total']} OK)", show_header=True)
    table.add_column("Package", style="white")
    table.add_column("Type", style="grey62")
    table.add_column("Status", justify="center")
    table.add_column("Required", justify="center")
    table.add_column("Description", style="grey62")

    status_colors = {"ok": "green", "missing": "red", "failed": "red", "will_install": "yellow", "installing": "blue", "installed": "green", "skipped": "grey62"}

    for d in deps["details"]:
        color = status_colors.get(d["status"], "white")
        table.add_row(
            d["name"],
            d["type"],
            f"[{color}]{d['status']}[/]",
            "Yes" if d["required"] else "No",
            d["description"],
        )

    console.print(table)

    # Capabilities
    caps = diagnostics["capabilities"]
    caps_text = Text()
    caps_text.append("Default Gateway: ", style="bold")
    caps_text.append(f"{caps['default_gateway']}\n")
    caps_text.append("Wi-Fi Info: ", style="bold")
    caps_text.append(f"{caps['wifi_info']}\n")
    caps_text.append("Admin/Root: ", style="bold")
    caps_text.append("Yes ✓\n" if caps['admin_access'] else "No ✗\n")
    caps_text.append("DNS Sniffer: ", style="bold")
    caps_text.append("Available ✓\n" if caps['dns_sniffer_available'] else "Unavailable (needs root/admin + tcpdump/Npcap)\n")
    caps_text.append("Package Manager: ", style="bold")
    caps_text.append(f"{caps['package_manager']}")

    console.print(Panel(caps_text, title="🔧 Capabilities", border_style="yellow"))

    # Network
    net = diagnostics["network"]
    net_text = Text()
    net_text.append("Interfaces: ", style="bold")
    net_text.append(f"{', '.join(net['interfaces']) if net['interfaces'] else 'None detected'}\n")
    net_text.append("ARP Entries: ", style="bold")
    net_text.append(f"{net['arp_entries']}")

    console.print(Panel(net_text, title="🌐 Network", border_style="blue"))

    # Summary
    if deps['missing'] > 0:
        console.print(Panel(
            f"[yellow]⚠️  {deps['missing']} missing dependencies. Run 'im install' to fix.[/yellow]",
            border_style="yellow",
        ))
    else:
        console.print(Panel(
            "[green]✅  All dependencies satisfied. Ready to run![/green]",
            border_style="green",
        ))


if __name__ == "__main__":
    app()