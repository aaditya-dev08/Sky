import subprocess
import sys
from pathlib import Path

try:
    from rich.console import Console
    from rich.prompt import Prompt
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "rich", "--quiet"])
    from rich.console import Console
    from rich.prompt import Prompt

console = Console()

if sys.stdout.encoding != "utf-8" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def main():
    console.print("\n[bold blue]☁️  Installing Sky...[/bold blue]\n")
    
    with console.status("[cyan]Installing sky from local source...[/cyan]", spinner="dots"):
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "sky-dev", "--quiet"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True
            )
        except subprocess.CalledProcessError:
            console.print("[red]❌ Installation failed.[/red]")
            sys.exit(1)
        
    # Verify installation succeeded
    try:
        ver_result = subprocess.run(["sky", "--version"], capture_output=True, text=True)
        if ver_result.returncode == 0:
            console.print(f"[green]✅ {ver_result.stdout.strip()} installed successfully![/green]")
        else:
            console.print("[red]❌ Installation failed during verification.[/red]")
            sys.exit(1)
    except FileNotFoundError:
        console.print("[red]❌ 'sky' command not found. Try restarting your terminal.[/red]")
        sys.exit(1)

    console.print("\n[bold]🚀 Sky is ready to use![/bold]")
    console.print("\n[dim]Choose your next step:[/dim]")
    console.print("  1. [cyan]Run sky init[/cyan] - Interactive setup (Recommended for first-time)")
    console.print("  2. [cyan]Run sky ask[/cyan] - Ask a quick test question")
    console.print("  3. [cyan]Skip[/cyan] - Exit")

    choice = Prompt.ask("Your choice", choices=["1", "2", "3"], default="1")

    if choice == "1":
        subprocess.run(["sky", "init"])
    elif choice == "2":
        subprocess.run(["sky", "ask", "What is this codebase about?"])
    else:
        console.print("[dim]Exiting... Run 'sky' anytime to get started.[/dim]")

if __name__ == "__main__":
    main()
