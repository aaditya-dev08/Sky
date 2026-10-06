"""Security guardrails for Sky — optimized pipeline."""

import asyncio
import logging
from typing import Dict, Any, Optional

from sky.security.sanitize import (
    sanitize_input,
    validate_tool_args,
    validate_path,
    validate_command,
)
from sky.security.detection import detect_prompt_injection
from sky.security.prompts import get_hardened_system_prompt
from sky.security.audit import log_security_event
from sky.security.guardrails_nvidia import get_guardrails as get_nvidia_guardrails

logger = logging.getLogger(__name__)


class SecurityGuardrails:
    """Optimized security pipeline with layered defense.
    
    Order:
    1. Regex guardrails FIRST (fast, <10ms) — block immediately if fails
    2. NVIDIA guardrails ONLY if regex passes (parallel execution)
    """
    
    def __init__(self, config=None, strict_mode: bool = True):
        self.config = config
        self.strict_mode = strict_mode
        self.nvidia = get_nvidia_guardrails()
        self.violations = []
    
    async def check_input_async(self, user_input: str) -> Dict[str, Any]:
        """Check user input with optimized pipeline."""
        sanitized = sanitize_input(user_input)
        if not sanitized:
            return {"passed": False, "reason": "Input is empty or contains only control characters", "layer": "sanitize", "sanitized_input": ""}

        # Step 1: Fast regex check (ALWAYS runs first)
        regex_result = self._check_regex(sanitized)
        if not regex_result["passed"]:
            logger.info(f"Regex blocked input: {regex_result['reason']}")
            # Log the violation
            self.violations.append((f"regex:{regex_result.get('category', 'unknown')}", regex_result.get("pattern", "")))
            log_security_event(regex_result.get('category', 'regex_block'), {"input": sanitized, "reason": regex_result['reason']})
            return {
                "passed": False,
                "reason": regex_result["reason"],
                "layer": "regex",
                "latency_ms": 5,
                "sanitized_input": sanitized,
                "suggestion": "Potential security violation detected. Please rephrase your request."
            }
        
        # Step 2: Check if NVIDIA guardrails should run
        if not self._nvidia_enabled():
            return {"passed": True, "reason": "Only regex enabled", "layer": "regex", "sanitized_input": sanitized}
        
        # Step 3: Run NVIDIA checks in PARALLEL
        nvidia_results = await self._check_nvidia_parallel(sanitized)
        
        # Combine results
        for result in nvidia_results:
            if not result["passed"]:
                logger.info(f"NVIDIA blocked input: {result['reason']}")
                self.violations.append((f"nvidia:{result.get('reason')}", ""))
                log_security_event("nvidia_guardrail_block", {"input": sanitized, "reason": result['reason']})
                return {
                    "passed": False,
                    "reason": result["reason"],
                    "suggestion": result.get("suggestion", "Please rephrase your request."),
                    "layer": "nvidia",
                    "latency_ms": 150,
                    "sanitized_input": sanitized
                }
        
        return {"passed": True, "reason": "All checks passed", "layer": "both", "sanitized_input": sanitized}
    
    def _check_regex(self, user_input: str) -> Dict[str, Any]:
        """Fast regex-based check (runs first)."""
        detections = detect_prompt_injection(user_input)
        if detections:
            first = detections[0]
            return {"passed": False, "reason": "Prompt injection detected", "category": "prompt_injection", "pattern": first.get('pattern')}
        
        # We don't run path/command validation on arbitrary chat input since it's just chat, 
        # but if we wanted to, we could. Path and command validations are usually for tool arguments.
        
        return {"passed": True, "reason": "Regex check passed"}
    
    def _nvidia_enabled(self) -> bool:
        """Check if NVIDIA guardrails are enabled."""
        if not self.nvidia.is_available():
            return False
        if self.config and hasattr(self.config, "guardrails"):
            return getattr(self.config.guardrails, "enabled", True)
        return True
    
    async def _check_nvidia_parallel(self, user_input: str) -> list:
        """Run NVIDIA guardrails in parallel."""
        tasks = []
        
        # Always run jailbreak check if enabled
        if not self.config or not hasattr(self.config, "guardrails") or getattr(self.config.guardrails, "check_input", True):
            tasks.append(self.nvidia.check_input_async(user_input))
        
        # Optionally run topic check
        if self.config and hasattr(self.config, "guardrails"):
            if getattr(self.config.guardrails, "check_topic", False):
                tasks.append(self.nvidia.check_topic_async(user_input))
        
        if not tasks:
            return []
            
        # Execute in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle exceptions gracefully
        processed = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"NVIDIA guardrail error: {result}")
                processed.append({"passed": True, "reason": "Guardrail error, failing open"})
            else:
                processed.append(result)
        
        return processed
    
    async def check_response_async(self, response: str) -> Dict[str, Any]:
        """Check model response with NVIDIA guardrails (if enabled)."""
        # Only run if explicitly enabled (default: off for performance)
        if not self.config or not hasattr(self.config, "guardrails"):
            return {"passed": True, "reason": "check_response disabled"}
        
        if not getattr(self.config.guardrails, "check_response", False):
            return {"passed": True, "reason": "check_response disabled"}
        
        if not self.nvidia.is_available():
            return {"passed": True, "reason": "NVIDIA unavailable"}
        
        return await self.nvidia.check_response_async(response)
    
    def process_user_input(self, user_input: str) -> tuple[bool, str, Optional[str]]:
        """Synchronous wrapper for backward compatibility."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If loop is running, create a new thread to run async
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, self.check_input_async(user_input))
                    result = future.result()
            else:
                result = loop.run_until_complete(self.check_input_async(user_input))
        except RuntimeError:
            result = asyncio.run(self.check_input_async(user_input))
            
        return result["passed"], result.get("sanitized_input", user_input), result.get("reason") if not result["passed"] else None
        
    def validate_tool_call(self, tool_name: str, args: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """Validate a tool call before execution."""
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

def get_security_guardrails(config=None) -> SecurityGuardrails:
    """Get or create the global security guardrails instance."""
    global _security_guardrails
    if _security_guardrails is None:
        _security_guardrails = SecurityGuardrails(config=config, strict_mode=True)
    else:
        if config:
            _security_guardrails.config = config
    return _security_guardrails
