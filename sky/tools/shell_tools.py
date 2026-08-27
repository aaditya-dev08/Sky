"""Shell execution tools with Docker sandboxing."""

import os
import subprocess
from typing import Any, Dict

from sky.config import load_config
from sky.tools.registry import RiskTier, register_tool


@register_tool("bash", "Execute a bash command in a sandboxed Docker container.", RiskTier.DESTRUCTIVE)
def bash(command: str, timeout: int = 60) -> Dict[str, Any]:
    """Run a bash command in a secure Docker sandbox.
    
    Args:
        command: The bash command to execute.
        timeout: Maximum execution time in seconds.
    """
    config = load_config()
    
    docker_image = config.docker_image
    # HARD-BLOCK constraint
    docker_network = "none" 
    
    workspace_dir = os.path.abspath(os.getcwd())
    
    docker_cmd = [
        "docker", "run", "--rm",
        f"--network={docker_network}",
        "--cap-drop=ALL",
        "--user=1000:1000",
        "-v", f"{workspace_dir}:/workspace:rw",
        "-w", "/workspace",
        docker_image,
        "bash", "-c", command
    ]
    
    try:
        result = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
            "success": result.returncode == 0
        }
    except subprocess.TimeoutExpired as e:
        return {
            "stdout": e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or ""),
            "stderr": e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or ""),
            "exit_code": 124,
            "success": False,
            "error": "Timeout expired"
        }
    except FileNotFoundError:
        return {
            "stdout": "",
            "stderr": "Docker executable not found. Ensure Docker is installed and in PATH.",
            "exit_code": -1,
            "success": False
        }
    except Exception as e:
        return {
            "stdout": "",
            "stderr": str(e),
            "exit_code": -1,
            "success": False
        }
