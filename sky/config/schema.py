"""Configuration schemas and loading utilities."""

import fnmatch
import os
import re
import yaml
import logging
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator
import pydantic

logger = logging.getLogger(__name__)


class ApprovalRuleConfig(BaseModel):
    """Configuration for tool call approval rules."""
    
    model_config = ConfigDict(extra="forbid")
    
    tool_name: Optional[str] = None
    path_pattern: Optional[str] = None
    max_lines_changed: Optional[int] = Field(default=None, ge=0)
    command_prefix: Optional[str] = None
    auto_approve: bool = True

    def matches(self, tool_name: str, args: Dict[str, Any]) -> bool:
        """Check if this rule matches a given tool call."""
        if self.tool_name and self.tool_name != tool_name:
            return False

        if self.path_pattern:
            # Assuming args might contain 'path' or 'file_path' indicating the file being modified
            path = args.get("path") or args.get("file_path") or args.get("TargetFile") or args.get("AbsolutePath")
            if not path or not fnmatch.fnmatch(str(path), self.path_pattern):
                return False

        if self.max_lines_changed is not None:
            # Rough heuristic: count newlines in diff or content args
            content = args.get("content") or args.get("diff") or args.get("CodeContent") or args.get("ReplacementContent")
            if content is not None:
                lines = len(re.findall(r"\n", str(content))) + 1
                if lines > self.max_lines_changed:
                    return False
            elif args.get("ReplacementChunks"):
                lines = 0
                for chunk in args.get("ReplacementChunks", []):
                    lines += len(re.findall(r"\n", str(chunk.get("ReplacementContent", "")))) + 1
                if lines > self.max_lines_changed:
                    return False

        if self.command_prefix:
            # Assuming args might contain 'command' or 'CommandLine'
            command = args.get("command") or args.get("CommandLine")
            if not command or not str(command).startswith(self.command_prefix):
                return False

        return True


class ModelInfoConfig(BaseModel):
    """Information about an available model."""
    id: str
    description: Optional[str] = None
    context_window: Optional[int] = None
    best_for: Optional[List[str]] = None
    provider: Optional[str] = None


class ProviderConfig(BaseModel):
    """Configuration for an LLM provider."""
    
    model_config = ConfigDict(extra="forbid")
    
    base_url: Optional[str] = None
    timeout: int = 60
    requires_api_key: bool = True
    free_tier: bool = False
    default_model: str
    models: List[ModelInfoConfig] = Field(default_factory=list)


class ModelAssignmentConfig(BaseModel):
    """Configuration for assigning a specific model to a role."""
    
    model_config = ConfigDict(extra="forbid")
    
    provider: str = Field(default="groq")
    model_id: str
    reasoning_effort: Optional[Literal["none", "low", "medium", "high"]] = None
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=1)
    description: Optional[str] = None


class ModelRoutingConfig(BaseModel):
    """Configuration for routing tasks to different models."""
    
    model_config = ConfigDict(extra="forbid")
    
    providers: Dict[str, ProviderConfig] = Field(default_factory=dict)
    roles: Dict[str, ModelAssignmentConfig]
    fallback: Optional[ModelAssignmentConfig] = None
    timeout_seconds: int = Field(default=30, ge=1)
    parallel_tool_calls: bool = True


class DexProjectConfig(BaseModel):
    """Main project configuration for SKY."""
    
    model_config = ConfigDict(extra="forbid")
    
    project_name: str = "sky-project"
    approval_rules: List[ApprovalRuleConfig] = Field(default_factory=list)
    max_retries: int = Field(default=3, ge=1, le=10)
    docker_image: str = "python:3.11-slim"
    docker_network: str = "none"
    max_turn_limit: int = Field(default=20, ge=1)
    context_chunk_size: int = Field(default=1000, ge=100)
    context_top_k: int = Field(default=5, ge=1)
    verbose: bool = False
    
    # Memory Settings
    memory_enabled: bool = Field(default=True, description="Enable project memory")
    memory_provider: str = Field(default="fastembed", description="Embedding provider (fastembed or sentence-transformers)")
    memory_chunk_size: int = Field(default=1000, description="Tokens per chunk")
    memory_chunk_overlap: int = Field(default=50, description="Overlap between chunks")
    memory_top_k: int = Field(default=5, description="Number of chunks to retrieve")
    memory_model: str = Field(default="all-MiniLM-L6-v2", description="Embedding model")
    memory_auto_index: bool = Field(default=False, description="Auto-index on first run")
    memory_auto_inject_on_ask: bool = Field(default=False, description="Auto-inject context on ask command")
    memory_exclude_patterns: List[str] = Field(
        default=[".git", "node_modules", "venv", "__pycache__", ".sky", ".pytest_cache", "*.pyc"],
        description="Excluded directories"
    )
    
    # Workflow Settings
    workflow_max_retries: int = Field(default=3, description="Maximum test-and-reflect retries")
    workflow_max_subtasks: int = Field(default=20, description="Max subtasks for decomposition")
    workflow_parallel_limit: int = Field(default=3, description="Limit for parallel subagents")
    workflow_enable_subagents: bool = Field(default=True, description="Enable subagents")
    workflow_enable_test_and_reflect: bool = Field(default=True, description="Enable test and reflect")
    workflow_checkpoint_interval: int = Field(default=10, description="Checkpoint interval")

    # Security Settings
    security_enabled: bool = Field(default=True, description="Enable security guardrails")
    security_strict_mode: bool = Field(default=True, description="Strict mode for guardrails")
    security_max_input_length: int = Field(default=10000, description="Max prompt length")
    security_allowed_extensions: List[str] = Field(
        default=[".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".sh", ".js", ".ts", ".html", ".css"],
        description="Allowed file extensions for writing"
    )
    security_dangerous_commands: List[str] = Field(
        default=["rm -rf", "dd if=", "mkfs", "format", "shred"],
        description="Dangerous commands to block"
    )

    @field_validator("memory_exclude_patterns")
    @classmethod
    def validate_exclude_patterns(cls, v: List[str]) -> List[str]:
        return [p for p in v if p.strip()]


def _get_config_paths() -> Tuple[Path, Path]:
    """Get the paths to global and local config files."""
    global_path = Path.home() / ".sky" / "config.yaml"
    local_path = Path("sky.yaml")
    return global_path, local_path


def load_config() -> DexProjectConfig:
    """Load and merge global and project configurations. Project config takes precedence."""
    global_path, local_path = _get_config_paths()
    config_data: Dict[str, Any] = {}

    if global_path.exists():
        try:
            with open(global_path, "r", encoding="utf-8") as f:
                global_data = yaml.safe_load(f)
                if global_data:
                    config_data.update(global_data)
        except Exception as e:
            logger.warning(f"Failed to load global config from {global_path}: {e}")

    if local_path.exists():
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                local_data = yaml.safe_load(f)
                if local_data:
                    config_data.update(local_data)
        except Exception as e:
            logger.warning(f"Failed to load local config from {local_path}: {e}")

    # Flatten memory settings if present
    if "memory" in config_data and isinstance(config_data["memory"], dict):
        mem_settings = config_data.pop("memory")
        for k, v in mem_settings.items():
            config_data[f"memory_{k}"] = v
            
    # Flatten workflow settings if present
    if "workflow" in config_data and isinstance(config_data["workflow"], dict):
        wf_settings = config_data.pop("workflow")
        for k, v in wf_settings.items():
            config_data[f"workflow_{k}"] = v
            
    # Flatten security settings if present
    if "security" in config_data and isinstance(config_data["security"], dict):
        sec_settings = config_data.pop("security")
        for k, v in sec_settings.items():
            config_data[f"security_{k}"] = v

    config = DexProjectConfig(**config_data)
    if os.getenv("SKY_VERBOSE", "").lower() == "true":
        config.verbose = True
        
    return config
def migrate_legacy_configs(config_dir: Path):
    """Migrate .env and models.yaml from project root to .sky/"""
    import shutil
    try:
        from rich.console import Console
        console = Console()
    except ImportError:
        console = None

    for file in [".env", "models.yaml"]:
        legacy_path = Path.cwd() / file
        new_path = config_dir / file
        if legacy_path.exists() and not new_path.exists():
            shutil.move(str(legacy_path), str(new_path))
            if console:
                console.print(f"[yellow]⚠️ Moved {file} to {config_dir}/{file}[/yellow]")


def get_config_dir(global_mode: bool = False) -> Path:
    """Get Sky configuration directory with priority:
    1. .sky/ in current or parent directory
    2. Fallback to .sky/ in current directory
    3. Global ~/.sky/ as last resort
    """
    if global_mode:
        global_dir = Path.home() / ".sky"
        global_dir.mkdir(parents=True, exist_ok=True)
        return global_dir

    # Check current and parent directories for .sky/
    current = Path.cwd()
    for parent in [current] + list(current.parents):
        sky_dir = parent / ".sky"
        if sky_dir.exists() and sky_dir.is_dir():
            migrate_legacy_configs(sky_dir)
            return sky_dir
    
    # Check global
    global_dir = Path.home() / ".sky"
    if global_dir.exists():
        return global_dir
    
    # Create local .sky/
    local_dir = current / ".sky"
    local_dir.mkdir(parents=True, exist_ok=True)
    migrate_legacy_configs(local_dir)
    return local_dir


def load_models_config(global_mode: bool = False) -> ModelRoutingConfig:
    """Load model routing configuration from .sky/models.yaml."""
    config_dir = get_config_dir(global_mode=global_mode)
    target_path = config_dir / "models.yaml"

    if not target_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {target_path}")

    try:
        with open(target_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if data:
                return ModelRoutingConfig(**data)
    except pydantic.ValidationError:
        raise
    except Exception as e:
        logger.warning(f"Failed to load models config from {target_path}: {e}")
        raise

    # Fallback default configuration
    return ModelRoutingConfig(
        providers={
            "groq": ProviderConfig(
                base_url="https://api.groq.com/openai/v1",
                timeout=30,
                requires_api_key=True,
                free_tier=True,
                default_model="openai/gpt-oss-120b",
                models=[
                    ModelInfoConfig(id="groq/compound-mini", description="Ultra-fast routing (0.1s)", context_window=8192, best_for=["routing", "classification"], provider="groq"),
                    ModelInfoConfig(id="openai/gpt-oss-120b", description="Best general conversation", context_window=128000, best_for=["general", "chat"], provider="groq"),
                    ModelInfoConfig(id="meta-models/Muse-Glimmer-30B", description="Dedicated reasoning & planning", context_window=32768, best_for=["planning", "reviewing"], provider="groq"),
                    ModelInfoConfig(id="qwen/qwen3.6-27b", description="Best-in-class tool calling", context_window=32768, best_for=["tool_calling", "execution"], provider="groq")
                ]
            ),
            "nim": ProviderConfig(
                base_url="https://integrate.api.nvidia.com/v1",
                timeout=60,
                requires_api_key=True,
                free_tier=True,
                default_model="mistralai/devstral-2",
                models=[
                    ModelInfoConfig(id="mistralai/devstral-2", description="Purpose-built for agentic coding", context_window=131072, best_for=["coding", "tool_use"], provider="nim"),
                    ModelInfoConfig(id="nvidia/llama-3.1-nemotron-70b-instruct", description="Reliable backup model", context_window=131072, best_for=["fallback"], provider="nim")
                ]
            )
        },
        roles={
            "general": ModelAssignmentConfig(provider="groq", model_id="openai/gpt-oss-120b", temperature=0.7),
            "planning": ModelAssignmentConfig(provider="groq", model_id="meta-models/Muse-Glimmer-30B", temperature=0.3),
            "reviewer": ModelAssignmentConfig(provider="groq", model_id="meta-models/Muse-Glimmer-30B", temperature=0.3),
            "routing": ModelAssignmentConfig(provider="groq", model_id="groq/compound-mini", temperature=0.0),
            "fast_loop": ModelAssignmentConfig(provider="groq", model_id="qwen/qwen3.6-27b", temperature=0.1),
            "coder": ModelAssignmentConfig(provider="nim", model_id="mistralai/devstral-2", temperature=0.1),
            "tester": ModelAssignmentConfig(provider="nim", model_id="mistralai/devstral-2", temperature=0.1),
        },
        fallback=ModelAssignmentConfig(provider="nim", model_id="nvidia/llama-3.1-nemotron-70b-instruct", temperature=0.1),
        timeout_seconds=30,
        parallel_tool_calls=True,
    )
