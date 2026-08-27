"""LangGraph multi-step workflow engine for SKY."""

from typing import TypedDict, List, Dict, Any, Optional, Literal, AsyncIterator
from dataclasses import dataclass, field
from enum import Enum
import json
import logging
from pathlib import Path
import asyncio

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.constants import START

from sky.config.schema import DexProjectConfig
from sky.storage.db import DatabaseManager
from sky.core.router import ModelRouter
from sky.core.approval import ApprovalGate
from sky.core.fast_loop import FastLoopEngine
from sky.core.subagent import SubagentRunner, SubagentRole
from sky.memory.indexer import RepoIndexer

logger = logging.getLogger(__name__)


class WorkflowStatus(str, Enum):
    """Workflow execution status."""
    PENDING = "pending"
    RUNNING = "running"
    REFINING = "refining"
    DECOMPOSING = "decomposing"
    EXECUTING = "executing"
    TESTING = "testing"
    REFLECTING = "reflecting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowState(TypedDict):
    """State for the LangGraph workflow."""
    # Input
    user_goal: str
    mode: str
    
    # Refinement
    refined_goal: str
    goal_confidence: float
    
    # Decomposition
    tasks: List[Dict[str, Any]]  # [{"id", "description", "dependencies", "estimated_effort", "tools_needed", "role"}]
    task_dag: Dict[str, List[str]]  # task_id -> [dependent_task_ids]
    
    # Execution
    current_task_index: int
    task_results: Dict[str, Any]  # task_id -> result
    task_status: Dict[str, str]  # task_id -> "pending|running|completed|failed"
    
    # Subagent
    subagent_results: List[Dict[str, Any]]
    
    # Testing
    test_results: Dict[str, Any]  # {"passed": int, "failed": int, "errors": List[str]}
    retry_count: int
    max_retries: int
    
    # Output
    diff: str
    final_summary: str
    status: WorkflowStatus
    
    # Metadata
    session_id: str
    turn_count: int


@dataclass
class WorkflowConfig:
    """Configuration for workflow execution."""
    max_retries: int = 3
    max_subtasks: int = 20
    parallel_limit: int = 3
    enable_subagents: bool = True
    enable_test_and_reflect: bool = True


class WorkflowEngine:
    """LangGraph-based workflow engine for multi-step SDLC."""
    
    def __init__(
        self,
        config: DexProjectConfig,
        db: DatabaseManager,
        router: ModelRouter,
        approval_gate: ApprovalGate,
        indexer: Optional[RepoIndexer] = None,
        checkpoint_dir: Optional[Path] = None,
    ):
        self.config = config
        self.db = db
        self.router = router
        self.approval_gate = approval_gate
        self.indexer = indexer
        self.checkpoint_dir = checkpoint_dir or Path.cwd() / ".sky" / "checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        
        self.workflow_config = WorkflowConfig(
            max_retries=getattr(config, "workflow_max_retries", 3),
            parallel_limit=getattr(config, "workflow_parallel_limit", 3)
        )
        
        self._graph = None
        self._checkpointer = None
        self._subagent_runner = None
    
    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow graph."""
        graph = StateGraph(WorkflowState)
        
        # Add nodes
        graph.add_node("refine_goal", self._refine_goal)
        graph.add_node("decompose", self._decompose)
        graph.add_node("build_dag", self._build_dag)
        graph.add_node("dispatch_subagents", self._dispatch_subagents)
        graph.add_node("run_tests", self._run_tests)
        graph.add_node("reflect", self._reflect)
        graph.add_node("summarize", self._summarize)
        
        # Add edges
        graph.add_edge(START, "refine_goal")
        graph.add_edge("refine_goal", "decompose")
        graph.add_edge("decompose", "build_dag")
        graph.add_edge("build_dag", "dispatch_subagents")
        graph.add_edge("dispatch_subagents", "run_tests")
        
        # Conditional edge for reflect
        graph.add_conditional_edges(
            "reflect",
            self._should_retry,
            {
                "retry": "dispatch_subagents",
                "summarize": "summarize",
                "fail": "summarize",
            }
        )
        
        graph.add_edge("run_tests", "reflect")
        graph.add_edge("summarize", END)
        
        return graph
    
    async def _emit(self, event: Dict[str, Any]) -> None:
        if hasattr(self, "event_queue") and self.event_queue:
            import asyncio
            if isinstance(self.event_queue, asyncio.Queue):
                await self.event_queue.put(event)
    
    async def _refine_goal(self, state: WorkflowState) -> WorkflowState:
        """Refine the user's goal using the planning model."""
        await self._emit({"type": "step", "step": "refining", "message": "🎯 Refining goal..."})
        logger.info("Refining goal...")
        
        messages = [
            {"role": "system", "content": """You are a goal refinement expert. Take the user's raw request and refine it into a clear, actionable software development goal.

Output should be a JSON object with:
- refined_goal: A clear, specific description of what needs to be done
- confidence: A number between 0 and 1 indicating how confident you are in understanding the goal
- questions: Any clarifying questions (if confidence < 0.7)

Be specific about what files or components might be involved."""},
            {"role": "user", "content": state["user_goal"]}
        ]
        
        response, was_fallback, model_used = await self.router.route(
            "planning",
            messages,
            expected_tool_calls=0,
        )
        
        content = response.get("content", "")
        
        # Parse JSON response
        try:
            # Extract JSON from markdown if needed
            import re
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                state["refined_goal"] = data.get("refined_goal", state["user_goal"])
                state["goal_confidence"] = data.get("confidence", 0.5)
            else:
                state["refined_goal"] = content
                state["goal_confidence"] = 0.5
        except json.JSONDecodeError:
            state["refined_goal"] = content
            state["goal_confidence"] = 0.5
        
        state["status"] = WorkflowStatus.REFINING.value
        await self._emit({"type": "step_complete", "step": "refining", "result": state["refined_goal"]})
        return state
    
    async def _decompose(self, state: WorkflowState) -> WorkflowState:
        """Decompose the goal into subtasks."""
        await self._emit({"type": "step", "step": "decomposing", "message": "Breaking down into tasks..."})
        logger.info("Decomposing goal into tasks...")
        
        messages = [
            {"role": "system", "content": """You are a task decomposition expert. Break down the goal into a structured set of subtasks.

Output should be a JSON array of tasks, each with:
- id: Unique identifier (e.g., "task_1", "task_2")
- description: Clear description of what to do
- dependencies: List of task IDs that must complete first
- estimated_effort: "small", "medium", or "large"
- tools_needed: List of tools required (e.g., ["read_file", "edit_file"])
- role: "planner", "coder", "tester", "reviewer"

Example:
[
    {"id": "task_1", "description": "Implement the requested feature", "dependencies": [], "estimated_effort": "medium", "tools_needed": ["read_file", "write_file", "edit_file"], "role": "coder"}
]

CRITICAL RULES:
1. For simple goals (like writing a single script or making a basic modification), use exactly ONE 'coder' task.
2. DO NOT over-complicate simple requests by splitting them into 'planning', 'setup', and 'coding' phases. 
3. Only use multiple tasks for complex features that require separate architectural planning or extensive multi-file changes.
4. Keep tasks atomic and focused. Max 10 tasks."""},
            {"role": "user", "content": f"Goal: {state.get('refined_goal', state['user_goal'])}"}
        ]
        
        response, was_fallback, model_used = await self.router.route(
            "planning",
            messages,
            expected_tool_calls=0,
        )
        
        content = response.get("content", "")
        
        # Parse JSON response
        try:
            import re
            json_match = re.search(r'\[.*\]', content, re.DOTALL)
            if json_match:
                tasks = json.loads(json_match.group())
                state["tasks"] = tasks
            else:
                # Fallback: create single task
                state["tasks"] = [{
                    "id": "task_1",
                    "description": state.get("refined_goal", state["user_goal"]),
                    "dependencies": [],
                    "estimated_effort": "medium",
                    "tools_needed": ["read_file", "write_file", "edit_file", "run_tests"],
                    "role": "coder"
                }]
        except json.JSONDecodeError:
            state["tasks"] = [{
                "id": "task_1",
                "description": state.get("refined_goal", state["user_goal"]),
                "dependencies": [],
                "estimated_effort": "medium",
                "tools_needed": ["read_file", "write_file", "edit_file", "run_tests"],
                "role": "coder"
            }]
        
        # Initialize task status
        state["task_status"] = {t["id"]: "pending" for t in state["tasks"]}
        state["task_results"] = {}
        if "subagent_results" not in state or not state["subagent_results"]:
            state["subagent_results"] = []
        state["status"] = WorkflowStatus.DECOMPOSING.value
        
        return state
    
    async def _build_dag(self, state: WorkflowState) -> WorkflowState:
        """Build the DAG from task dependencies."""
        logger.info("Building DAG...")
        
        dag = {}
        for task in state["tasks"]:
            dag[task["id"]] = task.get("dependencies", [])
        
        state["task_dag"] = dag
        state["status"] = WorkflowStatus.EXECUTING.value
        
        return state
    
    async def _dispatch_subagents(self, state: WorkflowState) -> WorkflowState:
        """Dispatch subagents for parallel task execution."""
        await self._emit({"type": "step", "step": "executing", "message": "🔧 Executing subagents..."})
        logger.info("Dispatching subagents...")
        
        # Get pending tasks
        pending_tasks = [
            t for t in state["tasks"]
            if state["task_status"].get(t["id"]) == "pending"
        ]
        
        if not pending_tasks:
            return state
        
        # Check dependencies
        available_tasks = []
        for task in pending_tasks:
            deps = task.get("dependencies", [])
            if all(state["task_status"].get(d) == "completed" for d in deps):
                available_tasks.append(task)
        
        if not available_tasks:
            # No tasks available - wait for dependencies
            return state
        
        # Limit parallel execution
        available_tasks = available_tasks[:self.workflow_config.parallel_limit]
        
        # Create subagent runner if not exists
        if self._subagent_runner is None:
            self._subagent_runner = SubagentRunner(
                config=self.config,
                db=self.db,
                router=self.router,
                approval_gate=self.approval_gate,
                indexer=self.indexer,
            )
        
        # Execute tasks in parallel using asyncio.gather
        tasks_coros = []
        for task in available_tasks:
            # Mark as running
            state["task_status"][task["id"]] = "running"
            
            # Get role
            role = SubagentRole(task.get("role", "coder"))
            
            # Emit task_start before running
            await self._emit({"type": "task_start", "task": task["id"], "message": f"🔧 Executing {task['id']}..."})
            
            # Create coroutine
            coro = self._subagent_runner.run(
                task=task,
                role=role,
                parent_state=state,
                event_queue=getattr(self, "event_queue", None)
            )
            tasks_coros.append(coro)
        
        results = await asyncio.gather(*tasks_coros)
        
        # Update state
        for result in results:
            task_id = result.get("task_id")
            await self._emit({"type": "task_result", "task": task_id, "result": result})
            if not result.get("success"):
                await self._emit({"type": "error", "content": f"Task {task_id} failed: {result.get('error')}"})
            state["task_status"][task_id] = "completed" if result.get("success") else "failed"
            state["task_results"][task_id] = result
            state["subagent_results"].append(result)
        
        state["status"] = WorkflowStatus.EXECUTING.value
        
        return state
    
    async def _run_tests(self, state: WorkflowState) -> WorkflowState:
        """Run tests after code changes."""
        await self._emit({"type": "step", "step": "testing", "message": "Running tests..."})
        logger.info("Running tests...")
        
        # Collect any test-related changes
        test_files = []
        for result in state.get("subagent_results", []):
            if result.get("test_results"):
                test_files.extend(result.get("test_files", []))
        
        # Run tests using the test tool
        from sky.tools.test_tools import run_tests
        
        try:
            # run_tests returns a dict matching exactly what we need
            result = run_tests(timeout=120)
            
            state["test_results"] = {
                "passed": result.get("passed", 0),
                "failed": result.get("failed", 0),
                "errors": result.get("errors", []),
                "success": result.get("success", False)
            }
            state["status"] = WorkflowStatus.TESTING.value
        except Exception as e:
            state["test_results"] = {
                "passed": 0,
                "failed": 1,
                "errors": [str(e)],
                "success": False
            }
        
        return state
    
    async def _reflect(self, state: WorkflowState) -> WorkflowState:
        """Reflect on test results and decide next action."""
        await self._emit({"type": "step", "step": "reflecting", "message": "Reflecting on results..."})
        logger.info("Reflecting on results...")
        
        test_results = state.get("test_results", {})
        passed = test_results.get("passed", 0)
        failed = test_results.get("failed", 0)
        errors = test_results.get("errors", [])
        
        if passed > 0 and failed == 0 and not errors:
            # All tests passed
            state["status"] = WorkflowStatus.COMPLETED.value
            return state
            
        if passed == 0 and failed == 0 and not errors:
            # No tests ran or found, but check if all tasks succeeded
            if all(status == "completed" for status in state["task_status"].values()):
                state["status"] = WorkflowStatus.COMPLETED.value
                return state
        
        # Check retry count
        retry_count = state.get("retry_count", 0)
        max_retries = state.get("max_retries", self.workflow_config.max_retries)
        
        if retry_count >= max_retries:
            # Max retries exceeded
            state["status"] = WorkflowStatus.FAILED.value
            return state
            
        await self._emit({"type": "step", "step": "retry", "message": f"Retrying tasks (attempt {retry_count + 1} of {max_retries})..."})
        
        # Prepare for retry
        state["retry_count"] = retry_count + 1
        state["status"] = WorkflowStatus.REFLECTING.value
        
        # Generate reflection message
        messages = [
            {"role": "system", "content": """You are a code reviewer. Analyze the test failures and suggest fixes.

Output a JSON with:
- analysis: Brief analysis of what went wrong
- suggested_fix: Description of what to change
- files_to_modify: List of file paths that need changes"""},
            {"role": "user", "content": f"""
Test Results:
- Passed: {passed}
- Failed: {failed}
- Errors: {errors}

Tasks completed: {[t for t in state['task_status'] if state['task_status'][t] == 'completed']}
Failed tasks: {[t for t in state['task_status'] if state['task_status'][t] == 'failed']}

Provide analysis and suggested fixes."""}
        ]
        
        response, was_fallback, model_used = await self.router.route(
            "planning",
            messages,
            expected_tool_calls=0,
        )
        
        content = response.get("content", "")
        
        # Parse reflection
        try:
            import re
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                reflection = json.loads(json_match.group())
                # Add failed tasks back to pending
                for task_id, status in state["task_status"].items():
                    if status == "failed":
                        state["task_status"][task_id] = "pending"
            else:
                # Fallback: retry failed tasks
                for task_id, status in state["task_status"].items():
                    if status == "failed":
                        state["task_status"][task_id] = "pending"
        except json.JSONDecodeError:
            # Fallback: retry failed tasks
            for task_id, status in state["task_status"].items():
                if status == "failed":
                    state["task_status"][task_id] = "pending"
        
        return state
    
    def _should_retry(self, state: WorkflowState) -> Literal["retry", "summarize", "fail"]:
        """Determine if workflow should retry."""
        status = state.get("status")
        
        if status == WorkflowStatus.COMPLETED.value:
            return "summarize"
        
        if status == WorkflowStatus.FAILED.value:
            return "fail"
        
        if status == WorkflowStatus.REFLECTING.value:
            retry_count = state.get("retry_count", 0)
            max_retries = state.get("max_retries", self.workflow_config.max_retries)
            
            if retry_count < max_retries:
                return "retry"
            else:
                return "fail"
        
        return "summarize"
    
    async def _summarize(self, state: WorkflowState) -> WorkflowState:
        """Generate final summary."""
        await self._emit({"type": "step", "step": "summarizing", "message": "Generating summary..."})
        logger.info("Generating summary...")
        
        # Collect results
        task_summary = []
        for task in state.get("tasks", []):
            task_id = task["id"]
            status = state["task_status"].get(task_id, "unknown")
            result = state["task_results"].get(task_id, {})
            
            task_summary.append({
                "id": task_id,
                "description": task["description"],
                "status": status,
                "result": result.get("summary", ""),
            })
        
        test_results = state.get("test_results", {})
        
        # Generate summary
        messages = [
            {"role": "system", "content": """You are a project summary expert. Create a clear, concise summary of the work completed.

Include:
1. What was accomplished
2. What was changed
3. Test results
4. Any issues or warnings
5. Next steps (if any)"""},
            {"role": "user", "content": f"""
Original Goal: {state['user_goal']}
Refined Goal: {state.get('refined_goal', state['user_goal'])}

Task Summary: {json.dumps(task_summary, indent=2)}

Test Results: {json.dumps(test_results, indent=2)}

Create a summary of the work."""}
        ]
        
        response, was_fallback, model_used = await self.router.route(
            "planning",
            messages,
            expected_tool_calls=0,
        )
        
        content = response.get("content", "")
        
        if state.get("status") != WorkflowStatus.FAILED.value:
            state["status"] = WorkflowStatus.COMPLETED.value
            
        await self._emit({"type": "complete", "summary": content})
            
        return state
    
    async def run_streaming(
        self,
        goal: str,
        mode: str = "agent",
        max_retries: int = 3,
        resume_from: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Run the workflow with real-time event streaming."""
        import asyncio
        self.event_queue = asyncio.Queue()
        
        # Start graph execution in background
        task = asyncio.create_task(self.run(goal, mode, max_retries, resume_from))
        
        while not task.done():
            try:
                event = await asyncio.wait_for(self.event_queue.get(), timeout=0.1)
                yield event
                if event.get("type") in ("complete", "error"):
                    break
            except asyncio.TimeoutError:
                continue
                
        # Make sure we didn't miss any events after task completion
        while not self.event_queue.empty():
            event = await self.event_queue.get()
            yield event
            
        await task
    
    async def run(
        self,
        goal: str,
        mode: str = "agent",
        max_retries: int = 3,
        resume_from: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run the workflow."""
        # Initialize state
        state: WorkflowState = {
            "user_goal": goal,
            "mode": mode,
            "refined_goal": "",
            "goal_confidence": 0.0,
            "tasks": [],
            "task_dag": {},
            "current_task_index": 0,
            "task_results": {},
            "task_status": {},
            "subagent_results": [],
            "test_results": {},
            "retry_count": 0,
            "max_retries": max_retries,
            "diff": "",
            "final_summary": "",
            "status": WorkflowStatus.PENDING.value,
            "session_id": self.db.create_session("workflow", goal),
            "turn_count": 0,
        }
        
        # Build graph
        self._graph = self._build_graph()
        
        # Setup checkpointer
        checkpoint_path = self.checkpoint_dir / f"{state['session_id']}.sqlite"
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        
        async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as checkpointer:
            # Compile graph
            app = self._graph.compile(checkpointer=checkpointer)
            
            # Run workflow
            config = {"configurable": {"thread_id": state["session_id"]}}
            
            # If resuming
            if resume_from:
                snapshot = await app.aget_state(config)
                if snapshot:
                    state = snapshot.values
            
            # Execute asynchronously
            async for event in app.astream(state, config):
                pass
                
            # Get final state
            final_state_snapshot = await app.aget_state(config)
            
            return final_state_snapshot.values
    
    async def resume(self, session_id: str) -> Dict[str, Any]:
        """Resume an interrupted workflow."""
        checkpoint_path = self.checkpoint_dir / f"{session_id}.sqlite"
        if not checkpoint_path.exists():
            raise ValueError(f"Session {session_id} not found")
        
        return await self.run(
            goal="Resume workflow",
            resume_from=session_id,
        )
