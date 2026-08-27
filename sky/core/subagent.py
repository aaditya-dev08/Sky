"""Subagent system for SKY workflow engine."""

from enum import Enum
from typing import Dict, List, Any, Optional, Literal
from dataclasses import dataclass, field
import logging
import json

from sky.config.schema import DexProjectConfig
from sky.storage.db import DatabaseManager
from sky.core.router import ModelRouter
from sky.core.approval import ApprovalGate
from sky.core.fast_loop import FastLoopEngine
from sky.memory.indexer import RepoIndexer

logger = logging.getLogger(__name__)


class SubagentRole(str, Enum):
    """Roles for subagents."""
    PLANNER = "planner"
    CODER = "coder"
    TESTER = "tester"
    REVIEWER = "reviewer"


@dataclass
class SubagentConfig:
    """Configuration for a subagent."""
    role: SubagentRole
    model_role: str  # Corresponds to models.yaml role
    tools: List[str] = field(default_factory=list)
    system_prompt_template: str = ""
    max_turns: int = 10
    temperature: float = 0.3


# Role-specific configurations
ROLE_CONFIGS = {
    SubagentRole.PLANNER: SubagentConfig(
        role=SubagentRole.PLANNER,
        model_role="planning",
        tools=["read_file", "grep", "glob", "git_diff", "git_log"],
        system_prompt_template="""You are a planning subagent for SKY.

Your role is to analyze the codebase and create a detailed plan.

Available tools: read_file, grep, glob, git_diff, git_log

Output a plan with:
1. What needs to be done
2. What files will be affected
3. Potential risks or dependencies
4. Estimated effort

Be thorough and specific.""",
        max_turns=5,
        temperature=0.3,
    ),
    SubagentRole.CODER: SubagentConfig(
        role=SubagentRole.CODER,
        model_role="fast_loop",
        tools=["read_file", "write_file", "edit_file", "grep", "glob", "git_diff", "git_commit", "git_branch"],
        system_prompt_template="""You are a coding subagent for SKY.

Your role is to implement code changes.

Available tools: read_file, write_file, edit_file, grep, glob, git_diff, git_commit, git_branch

Guidelines:
1. Read relevant files first
2. Make targeted changes
3. Use git_commit to commit changes
4. Explain what you changed and why

Be precise and focused.""",
        max_turns=10,
        temperature=0.1,
    ),
    SubagentRole.TESTER: SubagentConfig(
        role=SubagentRole.TESTER,
        model_role="fast_loop",
        tools=["read_file", "run_tests", "lint", "grep", "glob"],
        system_prompt_template="""You are a testing subagent for SKY.

Your role is to run tests and report results.

Available tools: read_file, run_tests, lint, grep, glob

Guidelines:
1. Run tests after code changes
2. Report pass/fail results
3. If tests fail, provide error details
4. Suggest fixes for failing tests

Be thorough and accurate.""",
        max_turns=5,
        temperature=0.1,
    ),
    SubagentRole.REVIEWER: SubagentConfig(
        role=SubagentRole.REVIEWER,
        model_role="planning",
        tools=["read_file", "grep", "glob", "git_diff", "git_log"],
        system_prompt_template="""You are a code reviewer subagent for SKY.

Your role is to review changes and provide feedback.

Available tools: read_file, grep, glob, git_diff, git_log

Guidelines:
1. Review the diff carefully
2. Check for code quality issues
3. Look for potential bugs or edge cases
4. Provide constructive feedback
5. Suggest improvements

Be critical but constructive.""",
        max_turns=5,
        temperature=0.3,
    ),
}


class SubagentRunner:
    """Runner for subagent execution."""
    
    def __init__(
        self,
        config: DexProjectConfig,
        db: DatabaseManager,
        router: ModelRouter,
        approval_gate: ApprovalGate,
        indexer: Optional[RepoIndexer] = None,
    ):
        self.config = config
        self.db = db
        self.router = router
        self.approval_gate = approval_gate
        self.indexer = indexer
    
    async def run(
        self,
        task: Dict[str, Any],
        role: SubagentRole,
        parent_state: Optional[Dict[str, Any]] = None,
        event_queue: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Run a subagent for a specific task."""
        logger.info(f"Running subagent {role} for task {task.get('id', 'unknown')}")
        
        if event_queue:
            import asyncio
            if isinstance(event_queue, asyncio.Queue):
                await event_queue.put({
                    "type": "subagent_start", 
                    "role": role.value, 
                    "task": task.get("description", "Unknown task")
                })
        
        # Get role configuration
        role_config = ROLE_CONFIGS.get(role)
        if not role_config:
            raise ValueError(f"Unknown role: {role}")
        
        # Build system prompt
        system_prompt = role_config.system_prompt_template
        
        # Add task-specific context
        if parent_state:
            context = self._build_context(parent_state)
            system_prompt = f"{system_prompt}\n\nContext from parent:\n{context}"
        
        # Build messages
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Task: {task.get('description', '')}\n\nDependencies: {task.get('dependencies', [])}\n\nRequired tools: {task.get('tools_needed', [])}"}
        ]
        
        # Create a fresh session for subagent
        session_id = self.db.create_session(f"subagent_{role.value}", task.get("id", "unknown"))
        
        # Initialize FastLoopEngine for this subagent
        engine = FastLoopEngine(
            config=self.config,
            db=self.db,
            router=self.router,
            approval_gate=self.approval_gate,
            session_id=session_id,
            indexer=self.indexer,
        )
        
        # Run the fast loop
        tool_filter = role_config.tools if role_config.tools else None
        
        responses = []
        try:
            async for event in engine.run(
                messages=messages,
                mode="agent",
                max_turns=role_config.max_turns,
                tools_filter=tool_filter,
                inject_context=False,  # Subagents don't auto-inject context
            ):
                if event_queue:
                    import asyncio
                    if isinstance(event_queue, asyncio.Queue):
                        if event.get("type") in ("tool_call", "tool_result", "error"):
                            await event_queue.put(event)
                            
                if event.get("type") == "final_answer":
                    responses.append(event.get("content", ""))
                elif event.get("type") == "error":
                    error_msg = event.get("content", event.get("error", "Unknown error"))
                    if event_queue:
                        import asyncio
                        if isinstance(event_queue, asyncio.Queue):
                            await event_queue.put({
                                "type": "subagent_complete", 
                                "role": role.value, 
                                "summary": f"Error: {error_msg}"
                            })
                    return {
                        "task_id": task.get("id"),
                        "success": False,
                        "error": error_msg,
                        "summary": "",
                    }
        except Exception as e:
            logger.error(f"Subagent {role} failed: {e}")
            if event_queue:
                import asyncio
                if isinstance(event_queue, asyncio.Queue):
                    await event_queue.put({
                        "type": "subagent_complete", 
                        "role": role.value, 
                        "summary": f"Failed: {str(e)}"
                    })
            return {
                "task_id": task.get("id"),
                "success": False,
                "error": str(e),
                "summary": "",
            }
        
        # Compress results
        summary = self._summarize_results(responses, role)
        
        if event_queue:
            import asyncio
            if isinstance(event_queue, asyncio.Queue):
                await event_queue.put({
                    "type": "subagent_complete", 
                    "role": role.value, 
                    "summary": summary
                })
        
        return {
            "task_id": task.get("id"),
            "role": role.value,
            "success": True,
            "responses": responses,
            "summary": summary,
            "session_id": session_id,
            "tool_usage": engine._tool_usage if hasattr(engine, "_tool_usage") else [],
        }
    
    def _build_context(self, parent_state: Dict[str, Any]) -> str:
        """Build context from parent state."""
        context_parts = []
        
        if parent_state.get("refined_goal"):
            context_parts.append(f"Goal: {parent_state['refined_goal']}")
        
        if parent_state.get("task_results"):
            completed = [
                f"{tid}: {res.get('summary', 'completed')}"
                for tid, res in parent_state["task_results"].items()
                if res.get("success")
            ]
            if completed:
                context_parts.append(f"Completed tasks:\n- " + "\n- ".join(completed))
        
        return "\n".join(context_parts) if context_parts else "No additional context"
    
    def _summarize_results(self, responses: List[str], role: SubagentRole) -> str:
        """Summarize subagent results."""
        if not responses:
            return "No output from subagent"
        
        # For testers, summarize test results
        if role == SubagentRole.TESTER:
            # Look for test results
            for response in responses:
                if "passed" in response.lower() or "failed" in response.lower():
                    # Extract test summary
                    lines = response.split("\n")
                    test_lines = [l for l in lines if "pass" in l.lower() or "fail" in l.lower() or "test" in l.lower()]
                    if test_lines:
                        return "\n".join(test_lines[:5])
        
        # Default: return first response truncated
        return responses[-1][:500] + ("..." if len(responses[-1]) > 500 else "")
