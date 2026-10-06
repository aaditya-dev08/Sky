"""Sky welcome header — Claude Code-style fieldset with logo."""

import json
import os
from pathlib import Path
from typing import List, Optional
from rich.console import Console

# Sky brand colors
SKY_BLUE = "#4A90D9"
ACCENT_TEAL = "#00D4AA"
GRAY = "#949494"
DIM = "#6C7086"

# Option B — Clean ASCII Art (readable, professional)
SKY_LOGO_ASCII = r"""
  ███████ ██   ██ ██    ██
  ██      ██  ██   ██  ██ 
  ███████ █████     ████  
       ██ ██  ██     ██   
  ███████ ██   ██    ██   
"""

def render_sky_logo() -> str:
    """Render the Sky logo as clean ASCII art."""
    return SKY_LOGO_ASCII

def get_username() -> str:
    """Get the username from config, or fall back to system username."""
    try:
        from sky.config.schema import get_config_dir
        config_dir = get_config_dir()
        user_config = config_dir / "user.json"
        if user_config.exists():
            with open(user_config) as f:
                data = json.load(f)
                return str(data.get("username", "Developer"))
    except Exception:
        pass
    
    return os.getenv("USER") or os.getenv("USERNAME") or "Developer"

def render_header(
    version: str = "0.1.10",
    user: Optional[str] = None,
    tips: Optional[List[str]] = None,
    whats_new: Optional[List[str]] = None,
) -> None:
    """Render the Sky welcome header."""
    console = Console()
    
    if user is None:
        user = get_username()
    
    if tips is None:
        tips = [
            "Ask Sky to explain your code",
            "Try: sky plan 'add feature X'",
            "Use sky agent for full execution",
        ]
    
    if whats_new is None:
        whats_new = [
            "Added NVIDIA Guardrails",
            "Faster CLI startup",
            "Dynamic model discovery",
        ]
    
    # Render ASCII logo
    logo = render_sky_logo()
    console.print(f"[bold {SKY_BLUE}]{logo}[/bold {SKY_BLUE}]")
    console.print(f"[dim]{' ' * 28}v{version}[/dim]")
    console.print()
    
    # Enlarged welcome message
    console.print(f"  [bold {ACCENT_TEAL}]Welcome back, {user}![/bold {ACCENT_TEAL}]")
    console.print()
    
    # Tips section
    console.print(f"  [bold {ACCENT_TEAL}]Tips for getting started[/bold {ACCENT_TEAL}]")
    for tip in tips:
        console.print(f"    • {tip}")
    console.print()
    
    # What's new section
    console.print(f"  [bold {ACCENT_TEAL}]What's new[/bold {ACCENT_TEAL}]")
    for item in whats_new:
        console.print(f"    • {item}")
    console.print(f"    [dim italic]/release-notes for more[/dim italic]")
    console.print()
