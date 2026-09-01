"""Chat mode for conversational interaction with Sky."""

from typing import Optional, List, Dict, Any
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from sky.config import load_config, load_models_config
from sky.core.router import ModelRouter
from sky.storage import get_db
from sky.core.fast_loop import FastLoopEngine
from sky.core.mode_prompts import get_mode_prompt

class ChatEngine:
    """Conversational chat engine for Sky."""
    
    def __init__(self, config, models_config, db, router):
        self.config = config
        self.models_config = models_config
        self.db = db
        self.router = router
        self.messages = []
        self.session_id = db.create_session("chat", "conversation")
        self.console = Console()
    
    def get_welcome_message(self) -> str:
        """Return welcome message with capabilities."""
        return """
        ☁️ **Sky Chat Mode**

        I'm Sky, your AI coding assistant. I can help you:

        • **Answer questions** about your codebase → `/ask`
        • **Plan features** with structured tasks → `/plan`  
        • **Write and edit code** with approval → `/agent`
        • **Run complex workflows** with subagents → `/workflow`

        **Try asking me:**
        - "What can you do?"
        - "Explain the approval gate"
        - "Help me fix a bug"
        - "Plan a new feature"

        Just type your message, and I'll guide you to the right tool!
        """
    
    def suggest_command(self, user_input: str) -> Optional[str]:
        """Suggest the right Sky command for the user's request."""
        # Simple keyword-based routing
        user_input_lower = user_input.lower()
        
        if any(word in user_input_lower for word in ["explain", "what", "how", "why", "tell me"]):
            return f"sky ask \"{user_input}\""
        
        if any(word in user_input_lower for word in ["fix", "bug", "error", "issue", "problem"]):
            return f"sky agent \"{user_input}\""
        
        if any(word in user_input_lower for word in ["plan", "design", "architecture", "feature"]):
            return f"sky plan \"{user_input}\""
        
        if any(word in user_input_lower for word in ["build", "add", "implement", "create", "workflow"]):
            return f"sky workflow \"{user_input}\""
        
        return None
    
    def run(self, initial_prompt: Optional[str] = None):
        """Run the chat loop."""
        import os
        if not os.getenv("GROQ_API_KEY") and not os.getenv("NVIDIA_NIM_API_KEY"):
            self.console.print("[yellow]⚠️ No API keys found. Run 'sky init' first.[/yellow]")
            return
            
        self.console.print(Panel(
            Markdown(self.get_welcome_message()),
            title="☁️ Sky Chat",
            border_style="cyan"
        ))
        
        if initial_prompt:
            self._process_user_message(initial_prompt)
        
        while True:
            user_input = Prompt.ask("\n[bold cyan]You[/bold cyan]")
            
            if user_input.lower() in ["exit", "quit", "bye"]:
                self.console.print("[dim]Goodbye! 👋[/dim]")
                break
            
            if user_input.startswith("/"):
                self._handle_command(user_input)
                continue
            
            self._process_user_message(user_input)
    
    def _process_user_message(self, user_input: str):
        """Process user message and generate response."""
        
        # Check if we should suggest a command
        suggested = self.suggest_command(user_input)
        
        if suggested:
            self.console.print(f"\n[dim]💡 I can help you with that! Try:[/dim]")
            self.console.print(f"  [bold cyan]{suggested}[/bold cyan]")
            
            if Confirm.ask("\n[dim]Would you like me to run this for you?[/dim]", default=False):
                self.console.print(f"\n[dim]⏳ Running: {suggested}[/dim]")
                # Execute the command
                import subprocess
                import shlex
                try:
                    parts = shlex.split(suggested)
                except ValueError:
                    parts = suggested.split()
                    
                if sys.platform == "win32":
                    cmd = ["python", "-m", "sky.cli"] + parts[1:]
                else:
                    cmd = parts
                subprocess.run(cmd, check=False)
                return
        
        # Fallback: use chat model for conversation
        import asyncio
        asyncio.run(self._get_chat_response(user_input))


    async def _get_chat_response(self, user_input: str):
        """Get response from chat model."""
        if not any(m.get("role") == "system" for m in self.messages):
            from sky.core.mode_prompts import get_mode_prompt
            self.messages.insert(0, {"role": "system", "content": get_mode_prompt("chat")})
            
        self.messages.append({"role": "user", "content": user_input})
        
        try:
            with self.console.status("[bold cyan]Thinking...", spinner="dots"):
                response, was_fallback, model_used = await self.router.route(
                    "general",
                    self.messages,
                    expected_tool_calls=0
                )
            
            content = response.get("content", "")
            
            self.console.print(f"\n[bold cyan]Sky[/bold cyan]")
            self.console.print(Markdown(content))
            
            self.messages.append({"role": "assistant", "content": content})
            
        except Exception as e:
            self.console.print(f"[red]Error: {e}[/red]")
    
    def _handle_command(self, user_input: str):
        """Handle slash commands."""
        import sys
        import shlex
        try:
            parts = shlex.split(user_input)
        except ValueError:
            parts = user_input.split()
            
        cmd = parts[0].lower()
        args = parts[1:]
        
        if cmd == "/ask":
            self.console.print("[dim]Switching to /ask mode...[/dim]")
            import subprocess
            if sys.platform == "win32":
                subprocess.run(["python", "-m", "sky.cli", "ask"] + args, check=False)
            else:
                subprocess.run(["sky", "ask"] + args, check=False)
        elif cmd == "/agent":
            self.console.print("[dim]Switching to /agent mode...[/dim]")
            import subprocess
            if sys.platform == "win32":
                subprocess.run(["python", "-m", "sky.cli", "agent"] + args, check=False)
            else:
                subprocess.run(["sky", "agent"] + args, check=False)
        elif cmd == "/workflow":
            self.console.print("[dim]Switching to /workflow mode...[/dim]")
            import subprocess
            if sys.platform == "win32":
                subprocess.run(["python", "-m", "sky.cli", "workflow"] + args, check=False)
            else:
                subprocess.run(["sky", "workflow"] + args, check=False)
        elif cmd == "/plan":
            self.console.print("[dim]Switching to /plan mode...[/dim]")
            import subprocess
            if sys.platform == "win32":
                subprocess.run(["python", "-m", "sky.cli", "plan"] + args, check=False)
            else:
                subprocess.run(["sky", "plan"] + args, check=False)
        else:
            self.console.print(f"[red]Unknown command: {cmd}[/red]")

import sys
