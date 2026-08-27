"""Git integration tools."""

import os
import subprocess
from typing import Any, Dict, List, Optional

from sky.tools.registry import RiskTier, register_tool


def _run_git(args: List[str]) -> subprocess.CompletedProcess:
    """Helper to run git commands safely."""
    try:
        return subprocess.run(["git"] + args, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Git command failed: {e.stderr}")
    except FileNotFoundError:
        raise RuntimeError("Git executable not found in PATH.")


@register_tool("git_diff", "Get git diffs for staged and unstaged changes.", RiskTier.SAFE)
def git_diff() -> Dict[str, Any]:
    """Get current git diff (unstaged and staged changes)."""
    unstaged = subprocess.run(["git", "diff"], capture_output=True, text=True).stdout
    staged = subprocess.run(["git", "diff", "--staged"], capture_output=True, text=True).stdout
    
    f_changed = subprocess.run(["git", "diff", "--name-only"], capture_output=True, text=True).stdout.splitlines()
    f_staged = subprocess.run(["git", "diff", "--staged", "--name-only"], capture_output=True, text=True).stdout.splitlines()
    
    return {
        "unstaged": unstaged,
        "staged": staged,
        "files_changed": [f for f in f_changed if f],
        "files_staged": [f for f in f_staged if f],
    }


@register_tool("git_log", "Get recent git commit history.", RiskTier.SAFE)
def git_log(limit: int = 10) -> List[Dict[str, Any]]:
    """Get git log history.
    
    Args:
        limit: Number of commits to return.
    """
    fmt = "%H|%an|%ae|%at|%s"
    try:
        result = _run_git(["log", f"--pretty=format:{fmt}", f"-n{limit}"])
    except RuntimeError:
        return []
        
    commits = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        parts = line.split("|", 4)
        if len(parts) == 5:
            commits.append({
                "hash": parts[0],
                "author_name": parts[1],
                "author_email": parts[2],
                "timestamp": parts[3],
                "subject": parts[4]
            })
    return commits


@register_tool("git_commit", "Commit changes to git repository.", RiskTier.DESTRUCTIVE)
def git_commit(message: str, files: Optional[List[str]] = None) -> Dict[str, Any]:
    """Commit files to the repository.
    
    Args:
        message: Commit message.
        files: Optional list of files to commit. If None, commits currently staged changes.
    """
    if files:
        _run_git(["add"] + files)
        
    try:
        _run_git(["commit", "-m", message])
        hash_result = _run_git(["rev-parse", "HEAD"])
        return {
            "hash": hash_result.stdout.strip(),
            "message": message,
            "files_committed": files or [],
            "success": True
        }
    except RuntimeError as e:
        return {
            "hash": "",
            "message": message,
            "files_committed": [],
            "success": False,
            "error": str(e)
        }


@register_tool("git_branch", "Create, switch, or view branches.", RiskTier.DESTRUCTIVE)
def git_branch(name: str, checkout: bool = False) -> Dict[str, Any]:
    """Create or checkout a git branch.
    
    Args:
        name: Name of the branch.
        checkout: Whether to switch to the branch.
    """
    if not os.path.exists(".git"):
        raise RuntimeError("Not a git repository (no .git directory found).")
        
    branches = _run_git(["branch", "--list", name]).stdout.strip()
    branch_exists = bool(branches)
    
    created = False
    switched = False
    
    try:
        if checkout:
            if branch_exists:
                _run_git(["checkout", name])
            else:
                _run_git(["checkout", "-b", name])
                created = True
            switched = True
        else:
            if not branch_exists:
                _run_git(["branch", name])
                created = True
                
        return {
            "branch": name,
            "created": created,
            "switched": switched,
            "success": True
        }
    except RuntimeError as e:
        return {
            "branch": name,
            "created": False,
            "switched": False,
            "success": False,
            "error": str(e)
        }
