"""Sky thinking component — live status line."""

import time
from rich.console import Console
from rich.status import Status

SKY_BLUE = "#4A90D9"
GRAY = "#949494"


class SkyThinking:
    """Context manager for the thinking status line."""
    
    def __init__(self, verb: str = "Thinking"):
        self.verb = verb
        self.console = Console()
        self.status = None
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        self.status = self.console.status(
            f"[{SKY_BLUE}]{self.verb}...[/{SKY_BLUE}]",
            spinner="dots"
        )
        self.status.__enter__()
        return self
    
    def __exit__(self, *args):
        elapsed = time.time() - self.start_time
        if self.status:
            self.status.__exit__(*args)
        self.console.print(f"  [dim]{self.verb} completed in {elapsed:.1f}s[/dim]")


def render_thinking(verb: str = "Thinking") -> SkyThinking:
    """Create a thinking status context."""
    return SkyThinking(verb)
