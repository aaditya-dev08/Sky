"""Model Router with F11 Batching Verification."""

from typing import Any, Dict, List, Optional, Tuple

import httpx
from openai import AsyncOpenAI

from sky.config import ModelAssignmentConfig, ModelRoutingConfig
from sky.storage import DatabaseManager
from sky.errors import ProviderError, ConfigurationError

class ModelRouter:
    """Routes requests to appropriate LLMs with F11 verification."""

    def __init__(self, config: ModelRoutingConfig, db: DatabaseManager, session_id: str):
        import os
        self.config = config
        self.db = db
        self.session_id = session_id
        
        self.clients = {}
        self.provider_keys = {}
        self.current_key_idx = {}
        
        for provider_name, provider_config in self.config.providers.items():
            if provider_config.requires_api_key:
                # Find keys for this provider, e.g., GROQ_API_KEY, NIM_API_KEY
                env_prefix = "NVIDIA_NIM" if provider_name == "nim" else provider_name.upper()
                keys = []
                for key_name in [f"{env_prefix}_API_KEY", f"{env_prefix}_API_KEY_2", f"{env_prefix}_API_KEY_3"]:
                    key = os.getenv(key_name)
                    if key:
                        keys.append(key)
                if not keys:
                    # Log a warning, but don't crash unless they try to use it
                    pass
                else:
                    self.provider_keys[provider_name] = keys
                    self.current_key_idx[provider_name] = 0
            else:
                self.provider_keys[provider_name] = ["dummy"]
                self.current_key_idx[provider_name] = 0
                
            self._init_client(provider_name)
        
    def _init_client(self, provider_name: str):
        """Initialize the client for a specific provider."""
        provider_config = self.config.providers.get(provider_name)
        if not provider_config:
            return
            
        keys = self.provider_keys.get(provider_name, [])
        if not keys:
            return
            
        idx = self.current_key_idx.get(provider_name, 0)
        api_key = keys[idx]
        
        kwargs = {
            "api_key": api_key,
            "timeout": httpx.Timeout(provider_config.timeout)
        }
        if provider_config.base_url:
            kwargs["base_url"] = provider_config.base_url
            
        self.clients[provider_name] = AsyncOpenAI(**kwargs)

    def get_model_for_role(self, role: str) -> ModelAssignmentConfig:
        """Get model config for a specific role."""
        if role in self.config.roles:
            return self.config.roles[role]
        return self.get_fallback_model()

    def get_fallback_model(self) -> ModelAssignmentConfig:
        """Get the fallback model config."""
        if self.config.fallback:
            return self.config.fallback
        return ModelAssignmentConfig(provider="nim", model_id="meta/llama-3.1-8b-instruct", reasoning_effort="none")

    def build_completion_params(
        self, 
        assignment: ModelAssignmentConfig, 
        messages: List[Dict[str, Any]], 
        tools: Optional[List[Dict[str, Any]]], 
        tool_choice: str, 
        parallel_tool_calls: bool
    ) -> Dict[str, Any]:
        """Build parameters for Groq API call."""
        params: Dict[str, Any] = {
            "model": assignment.model_id,
            "messages": messages,
        }
        if assignment.temperature is not None:
            params["temperature"] = assignment.temperature
        if assignment.max_tokens is not None:
            params["max_tokens"] = assignment.max_tokens
            
        if tools:
            params["tools"] = tools
            params["tool_choice"] = tool_choice
            params["parallel_tool_calls"] = parallel_tool_calls
            
        return params

    async def _call_with_rotation(self, params: Dict[str, Any], provider_name: str) -> Any:
        """Call API, rotating keys if rate limit is hit."""
        from rich.console import Console
        
        client = self.clients.get(provider_name)
        if not client:
            raise ConfigurationError(
                f"No active client for provider: {provider_name}.",
                code="SKY-001",
                suggestion=f"Add {provider_name.upper()}_API_KEY to .env or run `sky init`"
            )
            
        keys = self.provider_keys.get(provider_name, [])
        last_error = None
        
        for _ in range(max(1, len(keys))):
            try:
                return await client.chat.completions.create(**params)
            except Exception as e:
                error_str = str(e).lower()
                if any(err in error_str for err in ["413", "429", "rate limit", "rate_limit_exceeded"]):
                    last_error = e
                    if len(keys) > 1:
                        next_idx = (self.current_key_idx[provider_name] + 1) % len(keys)
                        Console().print(f"[yellow]{provider_name.upper()} API key rate limited. Rotating to next key (slot {next_idx + 1}/{len(keys)})...[/yellow]")
                        self.current_key_idx[provider_name] = next_idx
                        self._init_client(provider_name)
                        client = self.clients[provider_name]
                    else:
                        break
                else:
                    raise ProviderError(
                        f"Provider {provider_name} request failed: {e}",
                        code="SKY-002",
                        suggestion="Check your internet connection or run `sky check-providers` to verify availability."
                    )
                    
        raise ProviderError(
            f"Rate limit exceeded after exhausting all {len(keys)} keys.",
            code="SKY-003",
            suggestion="Wait 60 seconds. Consider using a different model or provider."
        )

    MAX_RETRY_ATTEMPTS = 2

    async def _retry_with_shortened_context(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]], role: str, attempt: int = 0) -> Tuple[Dict[str, Any], bool, str]:
        if attempt >= self.MAX_RETRY_ATTEMPTS:
            # Instead of returning an error dict, we raise to let fast_loop handle it or return a generic format
            raise Exception("Context too large even after truncation. Please try again with a simpler request.")
        
        # Keep system prompt + last user message
        if len(messages) >= 2:
            truncated = [messages[0], messages[-1]]
        else:
            truncated = messages
            
        # Recursive call, but need a way to increment attempt. 
        # Python doesn't easily let us pass 'attempt' directly to route() unless we add it to route's signature.
        # So we'll call route directly but wrapped in a try/except for the next attempt.
        assignment = self.get_model_for_role(role)
        params = self.build_completion_params(assignment, truncated, tools, "auto", self.config.parallel_tool_calls)
        try:
            chat_completion = await self._call_with_rotation(params, assignment.provider)
            resp = chat_completion.choices[0].message
            
            resp_dict: Dict[str, Any] = {
                "role": "assistant",
                "content": resp.content,
            }
            if resp.tool_calls:
                resp_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    } for tc in resp.tool_calls
                ]
            return resp_dict, False, assignment.model_id
        except Exception as e:
            if "reduce the length of the messages" in str(e).lower() or "context_length_exceeded" in str(e).lower():
                return await self._retry_with_shortened_context(truncated, tools, role, attempt=attempt + 1)
            raise

    async def route(
        self, 
        role: str, 
        messages: List[Dict[str, Any]], 
        tools: Optional[List[Dict[str, Any]]] = None, 
        expected_tool_calls: Optional[int] = None, 
        tool_choice: str = "auto"
    ) -> Tuple[Dict[str, Any], bool, str]:
        """Route request to model, returning (response_message_dict, was_fallback, model_used)."""
        if expected_tool_calls and expected_tool_calls > 1 and tools:
            resp, was_fallback = await self.verify_and_dispatch(role, messages, tools, expected_tool_calls, tool_choice)
            model_used = self.get_fallback_model().model_id if was_fallback else self.get_model_for_role(role).model_id
            return resp, was_fallback, model_used
            
        assignment = self.get_model_for_role(role)
        params = self.build_completion_params(assignment, messages, tools, tool_choice, self.config.parallel_tool_calls)
        
        try:
            chat_completion = await self._call_with_rotation(params, assignment.provider)
            resp = chat_completion.choices[0].message
        except Exception as e:
            if "reduce the length of the messages" in str(e).lower() or "context_length_exceeded" in str(e).lower():
                return await self._retry_with_shortened_context(messages, tools, role)
            raise
        
        if chat_completion.usage:
            cost = (chat_completion.usage.prompt_tokens + chat_completion.usage.completion_tokens) * 0.000001
            self.db.log_usage(
                self.session_id, 
                assignment.model_id, 
                role, 
                chat_completion.usage.prompt_tokens, 
                chat_completion.usage.completion_tokens, 
                cost, 
                0.0
            )
        
        resp_dict: Dict[str, Any] = {
            "role": "assistant",
            "content": resp.content,
        }
        if resp.tool_calls:
            resp_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                } for tc in resp.tool_calls
            ]
        return resp_dict, False, assignment.model_id

    async def verify_and_dispatch(
        self, 
        role: str, 
        messages: List[Dict[str, Any]], 
        tools: List[Dict[str, Any]], 
        expected_tool_calls: int = 1, 
        tool_choice: str = "auto"
    ) -> Tuple[Dict[str, Any], bool]:
        """F11 PRIMARY FUNCTION: Verify tool batching count and fallback if under-calling."""
        assignment = self.get_model_for_role(role)
        params = self.build_completion_params(assignment, messages, tools, tool_choice, True)
        
        chat_completion = await self._call_with_rotation(params, assignment.provider)
        resp = chat_completion.choices[0].message
        
        tool_call_count = len(resp.tool_calls) if resp.tool_calls else 0
        
        if tool_call_count < expected_tool_calls:
            self._log_fallback_event(assignment.model_id, tool_call_count, expected_tool_calls, "under_calling")
            
            fallback = self.get_fallback_model()
            fb_params = self.build_completion_params(fallback, messages, tools, tool_choice, True)
            fb_completion = await self._call_with_rotation(fb_params, fallback.provider)
            fb_resp = fb_completion.choices[0].message
            
            resp_dict: Dict[str, Any] = {
                "role": "assistant",
                "content": fb_resp.content,
            }
            if fb_resp.tool_calls:
                resp_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    } for tc in fb_resp.tool_calls
                ]
            return resp_dict, True
            
        resp_dict = {
            "role": "assistant",
            "content": resp.content,
        }
        if resp.tool_calls:
            resp_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                } for tc in resp.tool_calls
            ]
        return resp_dict, False

    def _log_fallback_event(self, model: str, actual: int, expected: int, reason: str) -> None:
        """Log fallback event to audit log."""
        self.db._write_audit_log(self.session_id, {
            "event": "fallback_triggered",
            "model": model,
            "actual_tool_calls": actual,
            "expected_tool_calls": expected,
            "reason": reason
        })
