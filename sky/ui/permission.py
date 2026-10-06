"""Sky permission component — approval prompt."""

from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

SKY_BLUE = "#4A90D9"
ACCENT_TEAL = "#00D4AA"
SUNSET_ORANGE = "#FF6B35"


def render_permission(
    tool_name: str,
    args: dict,
    options: Optional[list] = None,
) -> str:
    """Render a permission prompt and return user choice."""
    console = Console()
    
    if options is None:
        options = ["y", "n", "e"]
    
    # Build permission content
    content = f"[bold {SUNSET_ORANGE}]Action Required: Tool Execution Approval[/bold {SUNSET_ORANGE}]\n\n"
    content += f"[bold]Tool:[/bold] {tool_name}\n\n"
    
    for key, value in args.items():
        content += f"[bold]{key}:[/bold]\n"
        content += f"  {value[:200]}\n\n"
    
    console.print(Panel(
        content,
        border_style=SUNSET_ORANGE,
        padding=(1, 2),
    ))
    
    # Prompt user
    console.print("\n[bold]Approve execution?[/bold]")
    console.print(f"  [green]y[/green] - Approve and execute")
    console.print(f"  [red]n[/red] - Reject (skip this call)")
    console.print(f"  [yellow]e[/yellow] - Edit parameters and execute")
    
    choice = Prompt.ask("Your decision", choices=options, default="n")
    return choice
