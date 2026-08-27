"""Tool registry for defining and managing agent capabilities."""

import inspect
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, get_args, get_origin


class RiskTier(str, Enum):
    """Classification of tool execution risk."""
    
    SAFE = "safe"
    DESTRUCTIVE = "destructive"


@dataclass
class ToolDefinition:
    """Definition of an agent tool."""
    
    name: str
    description: str
    risk_tier: RiskTier
    func: Callable[..., Any]
    args_schema: Dict[str, Any]
    required_args: List[str] = field(default_factory=list)

    def to_openai_schema(self) -> Dict[str, Any]:
        """Convert the tool definition to OpenAI's function calling schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.args_schema,
                    "required": self.required_args,
                },
            },
        }


class ToolRegistry:
    """Singleton registry for all available tools."""
    
    _instance: Optional["ToolRegistry"] = None
    _tools: Dict[str, ToolDefinition]

    def __new__(cls) -> "ToolRegistry":
        if cls._instance is None:
            cls._instance = super(ToolRegistry, cls).__new__(cls)
            cls._instance._tools = {}
        return cls._instance

    @classmethod
    def _type_to_json_schema(cls, type_hint: Any) -> str:
        """Convert a Python type hint to a JSON Schema type string."""
        if type_hint == str:
            return "string"
        elif type_hint == int:
            return "integer"
        elif type_hint == float:
            return "number"
        elif type_hint == bool:
            return "boolean"
        elif type_hint == dict or type_hint == Dict:
            return "object"
        elif type_hint == list or type_hint == List:
            return "array"
        elif type_hint == Any:
            return "string"  # Fallback for Any
            
        origin = get_origin(type_hint)
        if origin is not None:
            # Handle Optional[...] which is Union[..., NoneType]
            import typing
            is_union = False
            try:
                import types
                if hasattr(types, "UnionType") and isinstance(type_hint, types.UnionType):
                    is_union = True
            except ImportError:
                pass
                
            if origin is typing.Union or is_union or type_hint.__class__.__name__ in ('_UnionGenericAlias', 'UnionType', 'Union') or "Union" in str(type_hint):
                args = get_args(type_hint)
                # Find the non-None type
                for arg in args:
                    if arg is not type(None):
                        return cls._type_to_json_schema(arg)
            
            # Handle List, Dict generics
            if origin == list or origin == typing.List or str(origin).endswith("list"):
                return "array"
            if origin == dict or origin == typing.Dict or str(origin).endswith("dict"):
                return "object"
                
        return "string"  # Default fallback

    @classmethod
    def _extract_param_description(cls, docstring: Optional[str], param_name: str) -> Optional[str]:
        """Extract parameter description from the docstring Args: section."""
        if not docstring:
            return None
            
        # Look for 'Args:' or 'Parameters:' section
        args_match = re.search(r"(?:Args|Parameters):\s*\n(.*?)(?:\n\s*\n|\Z)", docstring, re.DOTALL)
        if not args_match:
            return None
            
        args_section = args_match.group(1)
        
        # Look for the specific parameter description
        param_pattern = re.compile(rf"^\s*{param_name}\s*(?:\([^)]+\))?\s*:\s*(.*?)(?=\n\s*\w+\s*(?:\([^)]+\))?\s*:|\Z)", re.DOTALL | re.MULTILINE)
        
        param_match = param_pattern.search(args_section)
        if param_match:
            desc = param_match.group(1).replace("\n", " ").strip()
            return re.sub(r"\s+", " ", desc)
            
        return None

    def register(self, name: str, description: str, risk_tier: RiskTier) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator to register a function as a tool."""
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            sig = inspect.signature(func)
            docstring = inspect.getdoc(func)
            
            args_schema: Dict[str, Any] = {}
            required_args: List[str] = []
            
            for param_name, param in sig.parameters.items():
                if param_name == "self" or param_name == "cls":
                    continue
                    
                json_type = self._type_to_json_schema(param.annotation)
                param_desc = self._extract_param_description(docstring, param_name)
                
                param_schema: Dict[str, Any] = {"type": json_type}
                if param_desc:
                    param_schema["description"] = param_desc
                    
                args_schema[param_name] = param_schema
                
                if param.default == inspect.Parameter.empty:
                    required_args.append(param_name)
                    
            tool_def = ToolDefinition(
                name=name,
                description=description,
                risk_tier=risk_tier,
                func=func,
                args_schema=args_schema,
                required_args=required_args,
            )
            
            self._tools[name] = tool_def
            
            import os
            if os.getenv("SKY_VERBOSE", "").lower() == "true":
                from rich.console import Console
                import json
                Console().print(f"[dim]Schema for {name}: {json.dumps(tool_def.to_openai_schema(), indent=2)}[/dim]")
                
            return func
            
        return decorator

    def get(self, name: str) -> Optional[ToolDefinition]:
        """Get a tool definition by name."""
        return self._tools.get(name)

    def list(self, risk_tier: Optional[RiskTier] = None) -> List[ToolDefinition]:
        """List all tools, optionally filtered by risk tier."""
        if risk_tier:
            return [t for t in self._tools.values() if t.risk_tier == risk_tier]
        return list(self._tools.values())

    def get_schemas(self, risk_tier: Optional[RiskTier] = None) -> List[Dict[str, Any]]:
        """Get OpenAI function schemas for all tools, optionally filtered."""
        tools = self.list(risk_tier)
        return [t.to_openai_schema() for t in tools]

    def execute(self, name: str, **kwargs: Any) -> Any:
        """Execute a tool by name with the given arguments."""
        tool = self.get(name)
        if not tool:
            raise ValueError(f"Tool not found: {name}")
        return tool.func(**kwargs)


# Global registry instance and helper functions
_registry = ToolRegistry()


def register_tool(name: str, description: str, risk_tier: RiskTier) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a tool with the global registry."""
    return _registry.register(name, description, risk_tier)


def get_tool(name: str) -> Optional[ToolDefinition]:
    """Get a tool from the global registry."""
    return _registry.get(name)


def list_tools(risk_tier: Optional[RiskTier] = None) -> List[ToolDefinition]:
    """List tools from the global registry."""
    return _registry.list(risk_tier)


def get_tools_by_risk(risk_tier: RiskTier) -> List[ToolDefinition]:
    """Get tools matching a specific risk tier."""
    return _registry.list(risk_tier)


def get_tool_schemas(risk_tier: Optional[RiskTier] = None) -> List[Dict[str, Any]]:
    """Get OpenAI schemas from the global registry."""
    return _registry.get_schemas(risk_tier)
