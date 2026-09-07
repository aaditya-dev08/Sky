#!/usr/bin/env python3
"""Branded installation script for Sky."""

import subprocess
import sys
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

if sys.stdout.encoding != "utf-8" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def main():
    console.print("[bold cyan]☁️ Installing Sky...[/bold cyan]")
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("", total=None)
        
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "sky-dev", "--quiet"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True
            )
            progress.update(task, completed=100)
            console.print("[bold green]✅ Sky installed successfully![/bold green]")
            console.print()
            console.print("[dim]Try: sky ask 'hello'[/dim]")
            console.print("[dim]Or:  sky chat[/dim]")
        except subprocess.CalledProcessError:
            console.print("[red]❌ Installation failed. Please check your internet connection.[/red]")
            sys.exit(1)

if __name__ == "__main__":
    main()
