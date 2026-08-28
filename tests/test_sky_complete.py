import pytest
import subprocess
import os
import shutil
from pathlib import Path
import yaml
import time
import sys

# Constants
TEST_DIR = Path("test_sandbox")
SKY_CMD = ["sky"]

@pytest.fixture(scope="session", autouse=True)
def setup_sandbox():
    """Setup a sandbox directory for testing so we don't mess up the actual repo."""
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR)
    TEST_DIR.mkdir()
    
    # Create a dummy python file for tool reading tests
    with open(TEST_DIR / "dummy.py", "w") as f:
        f.write("def hello():\n    print('hello world')\n")
        
    # Create a dummy README.md for editing tests
    with open(TEST_DIR / "README.md", "w") as f:
        f.write("# Dummy Project\n")
        
    # Must copy the .env file so it has API keys for testing
    if Path(".env").exists():
        shutil.copy(".env", TEST_DIR / ".env")
        
    yield
    
    # Cleanup (optional, useful for debugging if we leave it)
    # if TEST_DIR.exists():
    #     shutil.rmtree(TEST_DIR)

def run_sky(args, cwd=TEST_DIR, timeout=60, input_str=None):
    """Run a sky command in the test sandbox."""
    # Ensure we use the python interpreter running pytest
    cmd = [sys.executable, "-m", "sky.cli"] + args
    
    env = os.environ.copy()
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            input=input_str,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env
        )
        return result
    except subprocess.TimeoutExpired as e:
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=-1,
            stdout=e.stdout.decode() if e.stdout else "",
            stderr=f"TIMEOUT EXPIRED ({timeout}s)"
        )


# --- Test 1: Environment Setup ---
def test_sky_imports():
    """Verify sky package imports correctly."""
    result = subprocess.run([sys.executable, "-c", "import sky; print(sky.__version__)"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "0.0.6" in result.stdout or "0.0.5" in result.stdout # Depending on if version was bumped yet

def test_sky_version():
    """Verify CLI version."""
    result = run_sky(["--version"])
    assert result.returncode == 0
    assert "SKY CLI Version" in result.stdout or "Sky version" in result.stdout


# --- Test 2: Configuration ---
def test_sky_init():
    """Verify sky init works."""
    # Run with --force and mock input for API keys (just hit enter to skip or use existing .env)
    result = run_sky(["init", "--force"], input_str="\n\n3\n")
    assert "models.yaml" in result.stdout
    assert (TEST_DIR / "models.yaml").exists()

def test_models_yaml_valid():
    """Verify models.yaml schema."""
    with open(TEST_DIR / "models.yaml", "r") as f:
        config = yaml.safe_load(f)
    assert "roles" in config
    assert "general" in config["roles"]


# --- Test 3: Provider Checks ---
def test_check_providers():
    """Verify check-providers runs successfully."""
    result = run_sky(["check-providers"])
    # If the user has a valid .env, this should say SUCCESS or at least output the table
    assert "Checking Providers" in result.stdout or "Status:" in result.stdout


# --- Test 4: Ask Mode ---
def test_ask_simple():
    """Verify simple ask mode."""
    result = run_sky(["ask", "Who are you?"])
    assert result.returncode == 0
    assert "Sky" in result.stdout or "I am" in result.stdout
    assert "Error" not in result.stdout
    assert "400" not in result.stdout

def test_ask_codebase():
    """Verify ask codebase doesn't trigger 400 token length loop."""
    result = run_sky(["ask", "What files are in this directory?"])
    assert result.returncode == 0
    assert "dummy.py" in result.stdout or "README.md" in result.stdout
    assert "400" not in result.stdout

def test_ask_with_tools():
    """Verify ask can read files."""
    result = run_sky(["ask", "What is inside dummy.py?"])
    assert result.returncode == 0
    assert "hello world" in result.stdout
    
    
# --- Test 5: Chat Mode ---
def test_chat_welcome():
    """Verify chat mode opens and closes."""
    result = run_sky(["chat"], input_str="exit\n")
    assert "Sky Chat Mode" in result.stdout
    assert "Goodbye" in result.stdout

def test_chat_identity():
    """Verify chat identity response."""
    result = run_sky(["chat"], input_str="Who built you?\nexit\n")
    assert "Aaditya A" in result.stdout


# --- Test 6: Agent Mode ---
def test_agent_read_file():
    """Verify agent can read files."""
    result = run_sky(["agent", "Read dummy.py and summarize it."])
    assert result.returncode == 0
    assert "hello world" in result.stdout or "print" in result.stdout

def test_agent_edit_file():
    """Verify agent editing file."""
    # Run agent and auto-approve by passing 'y' if it asks
    result = run_sky(["agent", "Add a comment to dummy.py that says 'Test comment'"], input_str="y\n")
    assert result.returncode == 0
    with open(TEST_DIR / "dummy.py", "r") as f:
        content = f.read()
    assert "Test comment" in content


# --- Test 7: Index Mode ---
def test_index_run():
    """Verify index command works on small repo."""
    result = run_sky(["index"])
    # May return code 0 or successfully index
    assert result.returncode == 0
    
def test_index_search():
    """Verify context search works."""
    run_sky(["index"]) # Ensure it's indexed
    result = run_sky(["context", "hello"])
    assert result.returncode == 0
    assert "dummy.py" in result.stdout


# --- Test 8: Observability ---
def test_stats():
    """Verify stats command."""
    result = run_sky(["stats"])
    assert result.returncode == 0
    assert "cost" in result.stdout.lower() or "sessions" in result.stdout.lower()

def test_sessions():
    """Verify sessions command."""
    result = run_sky(["sessions"])
    assert result.returncode == 0


# --- Test 9: Error Handling ---
def test_missing_api_key():
    """Verify behavior when API key is bad (if we can simulate it)."""
    env = os.environ.copy()
    env["GROQ_API_KEY"] = "bad_key"
    
    cmd = [sys.executable, "-m", "sky.cli", "ask", "hello"]
    result = subprocess.run(cmd, cwd=TEST_DIR, env=env, capture_output=True, text=True)
    # Should exit gracefully or print an error without looping
    assert "Error" in result.stdout or "SKY-" in result.stdout
