"""Sky tool call component — expandable tool details."""

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

SKY_BLUE = "#4A90D9"
ACCENT_TEAL = "#00D4AA"
GRAY = "#949494"


def render_tool_call(tool_name: str, args: dict, result: str = None) -> None:
    """Render a tool call with expandable output."""
    console = Console()
    
    # Tool header
    console.print(f"[{ACCENT_TEAL}]⏺[/{ACCENT_TEAL}] [bold]{tool_name}[/bold]")
    
    # Arguments
    for key, value in args.items():
        console.print(f"  [dim]{key}:[/dim] {value}")
    
    # Result (if provided)
    if result:
        console.print(f"  [{ACCENT_TEAL}]⎿[/{ACCENT_TEAL}] {result[:200]}...")
