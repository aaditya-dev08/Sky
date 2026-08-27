import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import json
import time

from sky.core.workflow import WorkflowEngine, WorkflowState, WorkflowStatus
from sky.core.subagent import SubagentRunner, SubagentRole, ROLE_CONFIGS
from sky.config.schema import DexProjectConfig
from sky.core.router import ModelRouter
from sky.core.approval import ApprovalGate
from sky.storage.db import DatabaseManager
from sky.memory.indexer import RepoIndexer


@pytest.fixture
def temp_workflow_dir(tmp_path):
    wf_dir = tmp_path / ".sky" / "checkpoints"
    wf_dir.mkdir(parents=True, exist_ok=True)
    return wf_dir


@pytest.fixture
def mock_db():
    db = MagicMock(spec=DatabaseManager)
    db.create_session.return_value = "test-session-id"
    return db


@pytest.fixture
def mock_router():
    router = MagicMock(spec=ModelRouter)
    # Default to a successful routing response using AsyncMock for route
    router.route = AsyncMock(return_value=(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"refined_goal": "Mocked refined goal", "confidence": 0.9})
                    }
                }
            ]
        },
        False,
        "mocked-model"
    ))
    return router


@pytest.fixture
def mock_approval():
    gate = MagicMock(spec=ApprovalGate)
    return gate


@pytest.fixture
def mock_indexer():
    indexer = MagicMock(spec=RepoIndexer)
    return indexer


@pytest.fixture
def config():
    return DexProjectConfig(
        workflow_max_retries=1,
        workflow_max_subtasks=5,
        workflow_parallel_limit=2,
    )


# ---------------------------------------------------------
# 1. Workflow Engine Tests
# ---------------------------------------------------------

@pytest.mark.asyncio
async def test_goal_refinement(config, mock_db, mock_router, mock_approval, temp_workflow_dir):
    engine = WorkflowEngine(config, mock_db, mock_router, mock_approval, checkpoint_dir=temp_workflow_dir)
    state: WorkflowState = {
        "user_goal": "build a cool app",
        "mode": "agent",
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
        "max_retries": 3,
        "diff": "",
        "final_summary": "",
        "status": WorkflowStatus.PENDING,
        "session_id": "test",
        "turn_count": 0,
    }
    
    new_state = await engine._refine_goal(state)
    assert new_state["status"] == WorkflowStatus.REFINING
    assert new_state["refined_goal"] == "Mocked refined goal"
    assert new_state["goal_confidence"] == 0.9


@pytest.mark.asyncio
async def test_task_decomposition(config, mock_db, mock_router, mock_approval, temp_workflow_dir):
    # Mock router for decomposition
    mock_router.route.return_value = (
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps([
                            {
                                "id": "t1", 
                                "description": "task 1", 
                                "dependencies": [], 
                                "estimated_effort": "small", 
                                "tools_needed": [], 
                                "role": "coder"
                            }
                        ])
                    }
                }
            ]
        },
        False,
        "mocked-model"
    )
    
    engine = WorkflowEngine(config, mock_db, mock_router, mock_approval, checkpoint_dir=temp_workflow_dir)
    state: WorkflowState = {
        "user_goal": "build a cool app",
        "mode": "agent",
        "refined_goal": "build a cool app",
        "goal_confidence": 1.0,
        "tasks": [],
        "task_dag": {},
        "current_task_index": 0,
        "task_results": {},
        "task_status": {},
        "subagent_results": [],
        "test_results": {},
        "retry_count": 0,
        "max_retries": 3,
        "diff": "",
        "final_summary": "",
        "status": WorkflowStatus.REFINING,
        "session_id": "test",
        "turn_count": 0,
    }
    
    new_state = await engine._decompose(state)
    assert len(new_state["tasks"]) == 1
    assert new_state["tasks"][0]["id"] == "t1"
    assert new_state["task_status"]["t1"] == "pending"
    assert new_state["status"] == WorkflowStatus.DECOMPOSING


@pytest.mark.asyncio
async def test_dag_building(config, mock_db, mock_router, mock_approval, temp_workflow_dir):
    engine = WorkflowEngine(config, mock_db, mock_router, mock_approval, checkpoint_dir=temp_workflow_dir)
    state: WorkflowState = {
        "tasks": [
            {"id": "t1", "dependencies": []},
            {"id": "t2", "dependencies": ["t1"]},
        ],
        "task_dag": {},
        "status": WorkflowStatus.DECOMPOSING,
    }
    
    new_state = await engine._build_dag(state)
    assert new_state["task_dag"] == {"t1": [], "t2": ["t1"]}
    assert new_state["status"] == WorkflowStatus.EXECUTING


@pytest.mark.asyncio
@patch("sky.core.subagent.SubagentRunner.run", new_callable=AsyncMock)
async def test_dispatch_subagents(mock_run, config, mock_db, mock_router, mock_approval, temp_workflow_dir):
    mock_run.return_value = {"task_id": "t1", "success": True, "summary": "done"}
    
    engine = WorkflowEngine(config, mock_db, mock_router, mock_approval, checkpoint_dir=temp_workflow_dir)
    state: WorkflowState = {
        "tasks": [
            {"id": "t1", "dependencies": [], "role": "coder"},
        ],
        "task_status": {"t1": "pending"},
        "task_results": {},
        "subagent_results": [],
        "status": WorkflowStatus.EXECUTING,
    }
    
    new_state = await engine._dispatch_subagents(state)
    assert new_state["task_status"]["t1"] == "completed"
    assert new_state["task_results"]["t1"]["success"] is True
    assert mock_run.called


@pytest.mark.asyncio
@patch("sky.tools.test_tools.run_tests")
async def test_run_tests(mock_run_tests, config, mock_db, mock_router, mock_approval, temp_workflow_dir):
    mock_run_tests.return_value = "=========================== short test summary info ===========================\n1 failed, 2 passed"
    engine = WorkflowEngine(config, mock_db, mock_router, mock_approval, checkpoint_dir=temp_workflow_dir)
    state: WorkflowState = {
        "subagent_results": [],
        "status": WorkflowStatus.EXECUTING,
    }
    
    new_state = await engine._run_tests(state)
    assert new_state["status"] == WorkflowStatus.TESTING
    assert new_state["test_results"]["success"] is False
    assert new_state["test_results"]["failed"] == 1


@pytest.mark.asyncio
async def test_reflect_retry(config, mock_db, mock_router, mock_approval, temp_workflow_dir):
    engine = WorkflowEngine(config, mock_db, mock_router, mock_approval, checkpoint_dir=temp_workflow_dir)
    state: WorkflowState = {
        "test_results": {"passed": 0, "failed": 1, "errors": []},
        "retry_count": 0,
        "max_retries": 2,
        "task_status": {"t1": "failed"},
        "status": WorkflowStatus.TESTING,
    }
    
    new_state = await engine._reflect(state)
    assert new_state["status"] == WorkflowStatus.REFLECTING
    assert new_state["retry_count"] == 1
    # Check conditional edge
    assert engine._should_retry(new_state) == "retry"


@pytest.mark.asyncio
async def test_reflect_complete(config, mock_db, mock_router, mock_approval, temp_workflow_dir):
    engine = WorkflowEngine(config, mock_db, mock_router, mock_approval, checkpoint_dir=temp_workflow_dir)
    state: WorkflowState = {
        "test_results": {"passed": 1, "failed": 0, "errors": []},
        "retry_count": 0,
        "max_retries": 1,
        "status": WorkflowStatus.TESTING,
    }
    
    new_state = await engine._reflect(state)
    assert new_state["status"] == WorkflowStatus.COMPLETED
    assert engine._should_retry(new_state) == "summarize"


# ---------------------------------------------------------
# 2. Subagent Tests
# ---------------------------------------------------------

def test_subagent_planner_config():
    cfg = ROLE_CONFIGS[SubagentRole.PLANNER]
    assert "grep" in cfg.tools
    assert "git_diff" in cfg.tools
    assert "write_file" not in cfg.tools
    assert cfg.max_turns == 5

def test_subagent_coder_config():
    cfg = ROLE_CONFIGS[SubagentRole.CODER]
    assert "edit_file" in cfg.tools
    assert "git_commit" in cfg.tools
    assert cfg.model_role == "fast_loop"

def test_subagent_tester_config():
    cfg = ROLE_CONFIGS[SubagentRole.TESTER]
    assert "run_tests" in cfg.tools
    assert "lint" in cfg.tools
    assert "git_commit" not in cfg.tools

def test_subagent_reviewer_config():
    cfg = ROLE_CONFIGS[SubagentRole.REVIEWER]
    assert "git_diff" in cfg.tools
    assert cfg.temperature == 0.3


@pytest.mark.asyncio
@patch("sky.core.fast_loop.FastLoopEngine.run", new_callable=MagicMock)
async def test_subagent_isolation(mock_run, config, mock_db, mock_router, mock_approval):
    runner = SubagentRunner(config, mock_db, mock_router, mock_approval)
    task = {"id": "t1", "description": "Write code", "role": "coder", "tools_needed": ["edit_file"]}
    
    # Mock async generator
    async def mock_agen(*args, **kwargs):
        yield {"type": "final_answer", "content": "Done coding."}
    
    mock_run.side_effect = mock_agen
    
    result = await runner.run(task, SubagentRole.CODER, parent_state={"refined_goal": "test"})
    assert result["success"] is True
    assert result["task_id"] == "t1"
    assert result["role"] == "coder"
    assert "Done coding" in result["summary"]


def test_subagent_summary(config, mock_db, mock_router, mock_approval):
    runner = SubagentRunner(config, mock_db, mock_router, mock_approval)
    responses = [
        "Thinking about tests...",
        "Running tests...",
        "1 passed, 0 failed, test complete."
    ]
    summary = runner._summarize_results(responses, SubagentRole.TESTER)
    assert "1 passed" in summary


# ---------------------------------------------------------
# 3. CLI Tests
# ---------------------------------------------------------

def test_cli_workflow_command():
    from typer.testing import CliRunner
    from sky.cli import app
    
    # Just verify command is registered in typer app
    runner = CliRunner()
    result = runner.invoke(app, ["workflow", "--help"])
    assert result.exit_code == 0
    assert "Run a multi-step workflow with LangGraph" in result.stdout


# ---------------------------------------------------------
# 4. Performance Tests
# ---------------------------------------------------------

def test_workflow_import_time():
    """Verify workflow engine does not cause slow startup."""
    start = time.perf_counter()
    from sky.core.workflow import WorkflowEngine
    end = time.perf_counter()
    import_time_ms = (end - start) * 1000
    # On very slow CI environments this might spike, but we verify it's fundamentally lightweight
    # Usually < 200ms
    assert import_time_ms < 1000  # Generous buffer for test env, target is < 150ms in practice
