"""SKY Core logic including Fast Loop, Model Router, and Approval Gate."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .approval import ApprovalGate
    from .fast_loop import FastLoopEngine
    from .router import ModelRouter
    from .workflow import WorkflowEngine, WorkflowState, WorkflowStatus
    from .subagent import SubagentRunner, SubagentRole, SubagentConfig

def get_approval_gate(*args, **kwargs):
    from .approval import ApprovalGate
    return ApprovalGate(*args, **kwargs)

def get_fast_loop_engine(*args, **kwargs):
    from .fast_loop import FastLoopEngine
    return FastLoopEngine(*args, **kwargs)

def get_model_router(*args, **kwargs):
    from .router import ModelRouter
    return ModelRouter(*args, **kwargs)

def get_workflow_engine(*args, **kwargs):
    from .workflow import WorkflowEngine
    return WorkflowEngine(*args, **kwargs)

def get_subagent_runner(*args, **kwargs):
    from .subagent import SubagentRunner
    return SubagentRunner(*args, **kwargs)

def get_mode_prompt(*args, **kwargs):
    from .mode_prompts import get_mode_prompt as _get_mode_prompt
    return _get_mode_prompt(*args, **kwargs)

__all__ = [
    "ApprovalGate",
    "FastLoopEngine",
    "ModelRouter",
    "get_mode_prompt",
    "WorkflowEngine",
    "WorkflowState",
    "WorkflowStatus",
    "SubagentRunner",
    "SubagentRole",
    "SubagentConfig",
    "ROLE_CONFIGS",
]
