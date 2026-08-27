"""Tool registry exports."""

from .registry import (
    RiskTier,
    ToolDefinition,
    ToolRegistry,
    get_tool,
    get_tool_schemas,
    get_tools_by_risk,
    list_tools,
    register_tool,
)

__all__ = [
    "RiskTier",
    "ToolDefinition",
    "ToolRegistry",
    "register_tool",
    "get_tool",
    "list_tools",
    "get_tools_by_risk",
    "get_tool_schemas",
]

# Ensure all tool modules are imported so their @register_tool decorators execute
from . import fs_tools, git_tools, search_tools, shell_tools
