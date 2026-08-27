"""Security guardrails for Sky."""

from typing import Optional, Dict, Any
import logging
from rich.console import Console

from sky.security.sanitize import (
    sanitize_input,
    validate_tool_args,
    validate_path,
    validate_command,
)
from sky.security.detection import detect_prompt_injection
from sky.security.prompts import get_hardened_system_prompt
from sky.security.audit import log_security_event

logger = logging.getLogger(__name__)
console = Console()


class SecurityGuardrails:
    """Main security guardrail class."""
    
    def __init__(self, strict_mode: bool = True):
        self.strict_mode = strict_mode
        self.violations = []
    
    def process_user_input(self, user_input: str) -> tuple[bool, str, Optional[str]]:
        """
        Process user input through security filters.
        
        Returns:
            (is_safe, sanitized_input, warning)
        """
        # Sanitize input
        sanitized = sanitize_input(user_input)
        
        if not sanitized:
            return False, "", "Input is empty or contains only control characters"
        
        # Check for prompt injection
        detections = detect_prompt_injection(sanitized)
        if detections:
            first_detection = detections[0]
            category = f"prompt_injection: {first_detection['category']}"
            pattern = first_detection['pattern']
            self.violations.append((category, pattern))
            log_security_event("prompt_injection", {"input": sanitized, "detections": detections})
            if self.strict_mode:
                return False, "", "Potential prompt injection detected. Please rephrase your request."
            else:
                return True, sanitized, "Potential prompt injection detected (allowed in non-strict mode)"
        
        return True, sanitized, None
    
    def validate_tool_call(self, tool_name: str, args: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate a tool call before execution.
        
        Returns:
            (is_valid, error_message)
        """
        if not validate_tool_args(tool_name, args):
            self.violations.append(("invalid_tool_args", f"{tool_name}: {args}"))
            log_security_event("invalid_tool_args", {"tool": tool_name, "args": args})
            return False, f"Invalid arguments for tool: {tool_name}"
        
        # Additional checks
        if tool_name in ['write_file', 'edit_file']:
            content = args.get('content', '')
            if len(content) > 1000000:  # 1MB limit
                log_security_event("large_file_content", {"tool": tool_name, "size": len(content)})
                return False, f"Content too large ({len(content)} bytes). Max 1MB."
        
        if tool_name == 'bash':
            command = args.get('command', '')
            # Blacklist dangerous commands
            dangerous_commands = ['rm -rf', 'dd if=', 'mkfs', 'format', 'shred']
            for dangerous in dangerous_commands:
                if dangerous in command.lower():
                    log_security_event("dangerous_command", {"command": command})
                    return False, f"Potentially dangerous command detected: {dangerous}"
        
        return True, None
    
    def get_hardened_prompt(self, base_prompt: str) -> str:
        """Get hardened system prompt."""
        return get_hardened_system_prompt(base_prompt)
    
    def get_violation_report(self) -> Dict[str, Any]:
        """Get report of all security violations."""
        return {
            "total_violations": len(self.violations),
            "violations": self.violations,
            "strict_mode": self.strict_mode,
        }

# Global instance
_security_guardrails: Optional[SecurityGuardrails] = None

def get_security_guardrails() -> SecurityGuardrails:
    """Get or create the global security guardrails instance."""
    global _security_guardrails
    if _security_guardrails is None:
        _security_guardrails = SecurityGuardrails(strict_mode=True)
    return _security_guardrails
