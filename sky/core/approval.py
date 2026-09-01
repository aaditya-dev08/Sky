"""Human Approval Gate for intercepting and approving destructive tool calls."""

import json
from typing import Any, Dict, Optional, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax
from rich.table import Table

from sky.config import DexProjectConfig
from sky.storage import DatabaseManager

console = Console()

class ApprovalGate:
    """Manages manual and automatic approvals for tool executions."""

    def __init__(self, config: DexProjectConfig, db: DatabaseManager, session_id: str):
        self.config = config
        self.db = db
        self.session_id = session_id

    def check_auto_approve(self, tool_name: str, args: Dict[str, Any]) -> Optional[bool]:
        """Check if a tool call matches any auto-approve rules in the config."""
        for rule in self.config.approval_rules:
            if not rule.auto_approve:
                continue
            if rule.matches(tool_name, args):
                return True
        return False

    def render_diff(self, content: str, filepath: str) -> Syntax:
        """Render unified diff with syntax highlighting."""
        return Syntax(content, "diff", theme="monokai", line_numbers=True)

    def render_command(self, command: str) -> Syntax:
        """Render bash command with syntax highlighting."""
        return Syntax(command, "bash", theme="monokai", line_numbers=False)

    def request_approval(self, tool_name: str, args: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """Request manual approval via rich interactive prompt."""
        console.print("\n")
        console.rule("[bold red]Action Required: Tool Execution Approval[/bold red]")
        console.print()
        
        table = Table(show_header=False, box=None)
        table.add_column("Property", style="cyan", justify="right")
        table.add_column("Value", style="white")
        
        table.add_row("Tool", f"[bold]{tool_name}[/bold]")
        
        if tool_name == "edit_file" and "diff" in args:
            table.add_row("File", args.get("path", "unknown"))
            console.print(table)
            console.print(Panel(self.render_diff(args["diff"], args.get("path", "")), title="Diff Preview", border_style="red"))
        elif tool_name == "bash" and "command" in args:
            table.add_row("Command", "")
            console.print(table)
            console.print(Panel(self.render_command(args["command"]), title="Bash Command", border_style="red"))
        else:
            args_str = json.dumps(args, indent=2)
            table.add_row("Arguments", args_str)
            console.print(table)
            
        console.print()
        console.rule(style="red")
        console.print()

        while True:
            response = Prompt.ask(
                "[bold yellow]Approve execution?[/bold yellow] [dim][y/n/e][/dim]",
                choices=["y", "n", "e"],
                default="y"
            )
            
            if response == "y":
                console.print("[green]Execution approved.[/green]")
                return True, "User approved", args
            elif response == "n":
                console.print("[red]Execution rejected.[/red]")
                return False, "User rejected", None
            elif response == "e":
                console.print("[dim]Editing parameters is not fully supported in this stub. Rejecting.[/dim]")
                return False, "User aborted to edit", None

    def process(self, tool_name: str, args: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """Main entry point to process a tool call through the approval gate."""
        # Check auto-approve first
        if self.check_auto_approve(tool_name, args):
            self.db.log_tool_call(self.session_id, tool_name, args, "destructive", "auto_approved")
            return True, "Auto-approved by rules", args
            
        # Fallback to manual approval
        approved, reason, final_args = self.request_approval(tool_name, args)
        
        decision = "approved" if approved else "rejected"
        self.db.log_tool_call(self.session_id, tool_name, final_args or args, "destructive", decision, approved_by="user")
        
        return approved, reason, final_args
