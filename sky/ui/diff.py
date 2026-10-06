"""Sky diff component — inline edit hunks."""

from rich.console import Console
from rich.syntax import Syntax

SKY_BLUE = "#4A90D9"
ACCENT_TEAL = "#00D4AA"
ROSE = "#cd694a"


def render_diff(file_path: str, diff: str) -> None:
    """Render a diff with syntax highlighting."""
    console = Console()
    
    # Header
    console.print(f"[bold {SKY_BLUE}]Update({file_path})[/bold {SKY_BLUE}]")
    
    # Diff content
    syntax = Syntax(diff, "diff", theme="monokai", line_numbers=False)
    console.print(syntax)
