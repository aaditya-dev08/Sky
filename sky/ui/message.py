"""Sky message component — user/assistant turns."""

from rich.console import Console
from rich.text import Text
from rich.panel import Panel

SKY_BLUE = "#4A90D9"
ACCENT_TEAL = "#00D4AA"
GRAY = "#949494"


def render_user_message(text: str) -> None:
    """Render a user message with ❯ prefix."""
    console = Console()
    console.print(f"[bold {ACCENT_TEAL}]❯[/bold {ACCENT_TEAL}] [white]{text}[/white]")


def render_assistant_message(text: str) -> None:
    """Render an assistant message."""
    console = Console()
    console.print(f"  {text}")


def render_message(text: str, role: str = "user") -> None:
    """Render a message based on role."""
    if role == "user":
        render_user_message(text)
    else:
        render_assistant_message(text)
