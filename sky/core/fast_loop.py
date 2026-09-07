"""Fast Loop Engine for iterative agent execution."""

import asyncio
import json
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from sky.config import DexProjectConfig
from sky.core.approval import ApprovalGate
from sky.core.mode_prompts import get_mode_prompt
from sky.core.router import ModelRouter
from sky.storage import DatabaseManager
from sky.tools.registry import RiskTier, get_tool, get_tool_schemas
from sky.security import get_security_guardrails


class FastLoopEngine:
    """Core engine for running the agent loop."""

    def __init__(self, config: DexProjectConfig, db: DatabaseManager, router: ModelRouter, session_id: str, approval_gate: Optional[ApprovalGate] = None, indexer: Optional[Any] = None):
        self.config = config
        self.db = db
        self.router = router
        self.approval_gate = approval_gate
        self.session_id = session_id
        self.indexer = indexer
        
        from rich.console import Console
        if self.approval_gate is None:
            Console().print("[bold yellow]WARNING: FastLoopEngine initialized without approval_gate. Destructive tools will be blocked.[/bold yellow]")
        else:
            if self.config.verbose:
                Console().print("[dim]approval_gate passed to FastLoopEngine[/dim]")

    def _get_available_tools(self, mode: str, tools_filter: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Filter tools based on mode and specific filter list."""
        all_schemas = get_tool_schemas()
        
        if mode == "ask":
            safe_schemas = []
            for schema in all_schemas:
                tool_def = get_tool(schema["function"]["name"])
                if tool_def and tool_def.risk_tier == RiskTier.SAFE:
                    safe_schemas.append(schema)
            all_schemas = safe_schemas
        elif mode == "agent":
            # Explicitly keep ALL tools for agent mode
            pass
            
        if tools_filter:
            all_schemas = [s for s in all_schemas if s["function"]["name"] in tools_filter]
            
        return all_schemas

    async def _execute_safe_tool(self, tool_call_id: str, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single safe tool asynchronously."""
        tool_def = get_tool(tool_name)
        if not tool_def:
            result_str = f"Error: Tool {tool_name} not found."
        else:
            try:
                result = tool_def.func(**args)
                result_str = json.dumps(result) if not isinstance(result, str) else result
            except Exception as e:
                result_str = f"Error: {e}"
                
        self.db.log_tool_call(self.session_id, tool_name, args, "safe", "auto_approved", result=result_str)
        
        return {
            "tool_call_id": tool_call_id,
            "role": "tool",
            "name": tool_name,
            "content": result_str,
        }

    async def _execute_destructive_tool(self, tool_call_id: str, tool_name: str, args: Dict[str, Any], mode: str) -> Dict[str, Any]:
        """Execute a destructive tool sequentially with approval gate."""
        from rich.console import Console
        console = Console()
        if self.config.verbose:
            console.print(f"[dim]_execute_destructive_tool called for {tool_name}[/dim]")
            
        tool_def = get_tool(tool_name)
        if not tool_def:
            result_str = f"Error: Tool {tool_name} not found."
            self.db.log_tool_call(self.session_id, tool_name, args, "destructive", "rejected", result=result_str)
            return {
                "tool_call_id": tool_call_id,
                "role": "tool",
                "name": tool_name,
                "content": result_str,
            }
            
        if self.approval_gate is None:
            console.print(f"[bold red]CRITICAL: approval_gate is None! Rejecting {tool_name}[/bold red]")
            return {
                "tool_call_id": tool_call_id,
                "role": "tool",
                "name": tool_name,
                "content": f"Execution rejected: approval_gate is not initialized.",
            }
            
        console.print() # Add a blank line
        approved, reason, final_args = self.approval_gate.process(tool_name, args)
        
        if self.config.verbose:
            console.print(f"[dim]approval_gate.process() returned decision: approved={approved}, reason={reason}[/dim]")
            
        if not approved:
            result_str = f"Execution rejected by user: {reason}"
        else:
            execute_args = final_args or args
            try:
                result = tool_def.func(**execute_args)
                result_str = json.dumps(result) if not isinstance(result, str) else result
            except Exception as e:
                result_str = f"Error: {e}"
                
        return {
            "tool_call_id": tool_call_id,
            "role": "tool",
            "name": tool_name,
            "content": result_str,
        }

    def _validate_tool_calls(self, tool_calls: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Validate that tool calls are well-formed JSON. Returns (valid_calls, error_results)."""
        valid_calls = []
        error_results = []
        for tc in tool_calls:
            try:
                if not isinstance(tc, dict):
                    raise ValueError("Tool call is not a dictionary")
                if "function" not in tc or "name" not in tc["function"]:
                    raise ValueError("Missing 'function' or 'name' in tool call")
                    
                tool_name = tc["function"]["name"]
                args_raw = tc["function"].get("arguments", "{}")
                
                if isinstance(args_raw, str):
                    try:
                        args_dict = json.loads(args_raw)
                    except json.JSONDecodeError as e:
                        raise ValueError(f"Arguments are not valid JSON: {e}")
                else:
                    args_dict = args_raw

                if getattr(self.config, "security_enabled", True):
                    guardrails = get_security_guardrails()
                    guardrails.strict_mode = getattr(self.config, "security_strict_mode", True)
                    is_valid, err_msg = guardrails.validate_tool_call(tool_name, args_dict)
                    if not is_valid:
                        error_results.append({
                            "tool_call_id": tc.get("id", "unknown"),
                            "role": "tool",
                            "name": tool_name,
                            "content": f"Security Guardrail Blocked: {err_msg}"
                        })
                        continue

                valid_calls.append(tc)
            except Exception as e:
                from rich.console import Console
                Console().print(f"[bold red]Skipping invalid tool call: {e}[/bold red]")
                error_results.append({
                    "tool_call_id": tc.get("id", "unknown") if isinstance(tc, dict) else "unknown",
                    "role": "tool",
                    "name": tc.get("function", {}).get("name", "unknown") if isinstance(tc, dict) and "function" in tc else "unknown",
                    "content": f"System Error: Invalid tool call format - {e}. You MUST use native JSON tool calls. DO NOT output XML."
                })
        return valid_calls, error_results

    async def _execute_tool_calls(self, tool_calls: List[Dict[str, Any]], mode: str) -> List[Dict[str, Any]]:
        """Execute a list of tool calls, handling risk tiers appropriately."""
        results = []
        safe_tasks = []
        
        valid_calls, error_results = self._validate_tool_calls(tool_calls)
        results.extend(error_results)
        
        for tc in valid_calls:
            tool_name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"])
            except Exception:
                args = {}
                
            tool_def = get_tool(tool_name)
            
            if tool_def and tool_def.risk_tier == RiskTier.SAFE:
                safe_tasks.append(self._execute_safe_tool(tc["id"], tool_name, args))
            else:
                if safe_tasks:
                    safe_results = await asyncio.gather(*safe_tasks)
                    results.extend(safe_results)
                    safe_tasks = []
                    
                res = await self._execute_destructive_tool(tc["id"], tool_name, args, mode)
                results.append(res)
                
        if safe_tasks:
            safe_results = await asyncio.gather(*safe_tasks)
            results.extend(safe_results)
            
        return results

    def _get_relevant_context(self, query: str) -> str:
        """Retrieve relevant context for the query if memory is enabled."""
        if not self.indexer or not getattr(self.config, "memory_enabled", False):
            return ""
            
        from rich.console import Console
        if self.config.verbose:
            Console().print(f"[dim]Retrieving context for query...[/dim]")
            
        context = self.indexer.get_context(query, top_k=getattr(self.config, "memory_top_k", 5))
        if not context:
            return ""
            
        return str(context)
    MAX_MESSAGES = 10
    MAX_MESSAGE_LENGTH = 2000

    def _truncate_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Truncate messages to prevent token overflow."""
        if len(messages) > self.MAX_MESSAGES:
            # Keep system prompt if it's the first message, and the most recent messages
            if messages and messages[0].get("role") == "system":
                messages = [messages[0]] + messages[-(self.MAX_MESSAGES - 1):]
            else:
                messages = messages[-self.MAX_MESSAGES:]
        
        for i, msg in enumerate(messages):
            if "content" in msg and msg["content"]:
                content_str = str(msg["content"])
                if len(content_str) > self.MAX_MESSAGE_LENGTH:
                    msg["content"] = content_str[:self.MAX_MESSAGE_LENGTH] + "...(truncated)"
        
        return messages

    async def run(
        self, 
        messages: List[Dict[str, Any]], 
        mode: str, 
        system_prompt: Optional[str] = None, 
        max_turns: Optional[int] = None, 
        tools_filter: Optional[List[str]] = None,
        inject_context: bool = False
    ) -> AsyncIterator[Dict[str, Any]]:
        """Run the main agent loop streaming events."""
        turn_limit = max_turns or self.config.max_turn_limit
        if getattr(self.config, "security_enabled", True):
            from sky.security.prompts import get_system_prompt_with_guardrails, get_hardened_system_prompt
            if system_prompt:
                prompt = get_hardened_system_prompt(system_prompt)
            else:
                prompt = get_system_prompt_with_guardrails(mode)
        else:
            prompt = system_prompt or get_mode_prompt(mode)
        
        # Get context from first user message
        user_query = ""
        for msg in messages:
            if msg.get("role") == "user":
                user_query = str(msg.get("content", ""))
                break
                
        from sky.core.mode_prompts import format_context_prompt
        if inject_context and self.indexer and getattr(self.config, "memory_enabled", False):
            context = self._get_relevant_context(user_query)
            prompt = format_context_prompt(prompt, context)
        else:
            prompt = format_context_prompt(prompt, "")
            
        if getattr(self.config, "security_enabled", True):
            from sky.security.sanitize import validate_context_size
            if not validate_context_size(messages, max_tokens=getattr(self.config, "security_max_input_length", 10000)):
                yield {"type": "error", "message": "Context size exceeds limit. Please start a new session."}
                return
            
        if not messages or messages[0].get("role") != "system":
            messages.insert(0, {"role": "system", "content": prompt})
        else:
            messages[0]["content"] = prompt
            
        tools = self._get_available_tools(mode, tools_filter)
        
        # Get mode-to-role mapping from config
        mode_roles = getattr(self.config, "mode_roles", {})
        role = mode_roles.get(mode, "fast_loop")
        
        if self.config.verbose:
            from rich.console import Console
            Console().print(f"[dim]Available tools for {mode}: {[t['function']['name'] for t in tools]}[/dim]")
            if not tools:
                Console().print("[yellow]Warning: No tools available. Check configuration.[/yellow]")
        
        consecutive_tool_failures = 0
        
        for turn in range(turn_limit):
            yield {"type": "turn_start", "turn": turn + 1}
            
            expected = 1
            
            try:
                messages = self._truncate_messages(messages)
                
                if self.config.verbose:
                    from rich.console import Console
                    Console().print("[dim]Calling router.route() with 60s timeout...[/dim]")
                    
                response_msg, was_fallback, model_used = await asyncio.wait_for(
                    self.router.route(
                        role=role,
                        messages=messages,
                        tools=tools if tools else None,
                        expected_tool_calls=expected if tools else None
                    ),
                    timeout=60.0
                )
            except asyncio.TimeoutError:
                yield {"type": "error", "content": "Request timed out after 60 seconds. The model took too long to respond."}
                break
            except Exception as e:
                error_str = str(e)
                if "reduce the length" in error_str.lower() or "context_length_exceeded" in error_str.lower():
                    yield {"type": "error", "content": "The codebase/files returned too much data and exceeded the model's context limit. Please try asking a more specific question or using smaller files."}
                    break

                if "tool call validation failed" in error_str or "invalid_request_error" in error_str or "400" in error_str:
                    consecutive_tool_failures += 1
                    if consecutive_tool_failures >= 3:
                        yield {"type": "error", "error": "Model stuck in tool validation loop after 3 attempts. Aborting.", "suggestion": "Try rephrasing your request."}
                        return
                        
                    from rich.console import Console
                    Console().print(f"[yellow]Model tool validation failed: {error_str}. Feeding error back to model...[/yellow]")
                    messages.append({
                        "role": "user",
                        "content": f"System Error: Your last response triggered an API validation error: {error_str}\n\nYou MUST use native JSON tool calls. DO NOT output XML pseudo-tags like <tool_call>. Only call tools that are explicitly provided in the schema."
                    })
                    continue
                else:
                    raise e
            
            consecutive_tool_failures = 0
            
            messages.append(response_msg)
            
            yield {
                "type": "model_response", 
                "message": response_msg, 
                "was_fallback": was_fallback, 
                "model": model_used
            }
            
            if "tool_calls" in response_msg and response_msg["tool_calls"]:
                needs_approval = False
                for tc in response_msg["tool_calls"]:
                    if "function" in tc:
                        tool_name = tc["function"].get("name", "unknown")
                        tool_def = get_tool(tool_name)
                        if tool_def and tool_def.risk_tier != RiskTier.SAFE:
                            needs_approval = True
                        
                        yield {
                            "type": "tool_call",
                            "tool_name": tool_name,
                            "args": tc["function"].get("arguments", "{}")
                        }
                        
                if needs_approval:
                    yield {"type": "waiting", "message": "Waiting for user approval..."}
            
                tool_results = await self._execute_tool_calls(response_msg["tool_calls"], mode)
                messages.extend(tool_results)
                
                for res in tool_results:
                    yield {
                        "type": "tool_result",
                        "tool_name": res.get("name", "unknown"),
                        "result": res.get("content", "")
                    }
                
                yield {"type": "tool_results", "results": tool_results}
            else:
                yield {"type": "final_answer", "content": response_msg.get("content", "")}
                break
        else:
            error_msg = (
                f"Reached maximum turns ({turn_limit}). The model may be stuck in a loop.\n"
                f"Suggestion: Try rephrasing your request, using a simpler command, or use `sky ask` instead of `sky agent` for complex conceptual queries."
            )
            yield {"type": "error", "content": error_msg}
