"""Filesystem manipulation tools."""

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

import patch

from sky.tools.registry import RiskTier, register_tool


def _resolve_and_validate_path(path_str: str) -> Path:
    """Resolve a path and ensure it stays within the current working directory."""
    cwd = Path.cwd().resolve()
    target_path = Path(path_str).expanduser().resolve()
    
    try:
        # Check if the target_path is relative to cwd (prevents traversal)
        target_path.relative_to(cwd)
    except ValueError:
        raise PermissionError(f"Path traversal attempt blocked: {path_str} resolves outside of project root {cwd}")
        
    return target_path


@register_tool("read_file", "Read content from a file safely.", RiskTier.SAFE)
def read_file(path: str, offset: Optional[int] = None, limit: Optional[int] = None) -> str:
    """Read contents of a file with optional line ranges.
    
    Args:
        path: Path to the file to read.
        offset: Optional starting line number (1-indexed).
        limit: Optional maximum number of lines to read.
    """
    target = _resolve_and_validate_path(path)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    with open(target, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
        
    if offset is not None:
        if offset < 1:
            raise ValueError("Offset must be >= 1 (1-indexed).")
        lines = lines[offset - 1:]
        
    if limit is None or limit > 1000:
        limit = 1000
        
    if limit < 1:
        raise ValueError("Limit must be >= 1.")
    lines = lines[:limit]
        
    return "".join(lines)


@register_tool("write_file", "Write content to a file atomically.", RiskTier.DESTRUCTIVE)
def write_file(path: str, content: str) -> Dict[str, Any]:
    """Write complete content to a file.
    
    Args:
        path: Path to the file to write.
        content: The complete content to write.
    """
    target = _resolve_and_validate_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    
    fd, temp_path = tempfile.mkstemp(dir=target.parent, prefix=".tmp_sky_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(temp_path, target)
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise OSError(f"Failed to write file atomically: {e}")

    return {
        "path": str(target.relative_to(Path.cwd())),
        "bytes_written": len(content.encode("utf-8")),
        "success": True
    }


@register_tool("edit_file", "Apply a unified diff to a file.", RiskTier.DESTRUCTIVE)
def edit_file(path: str, diff: str) -> Dict[str, Any]:
    """Edit a file by applying a unified diff patch.
    
    Args:
        path: Path to the file to edit.
        diff: The unified diff string to apply.
    """
    target = _resolve_and_validate_path(path)
    if not target.exists():
        raise FileNotFoundError(f"Cannot edit non-existent file: {path}")

    patch_set = patch.fromstring(diff.encode("utf-8"))
    if not patch_set or not patch_set.items:
        raise ValueError("Invalid unified diff provided.")

    if len(patch_set.items) > 1:
        raise ValueError("Diff contains multiple files. Use edit_file for one file at a time.")
        
    import shutil
    with tempfile.TemporaryDirectory(dir=target.parent) as temp_dir:
        temp_dir_path = Path(temp_dir)
        temp_target = temp_dir_path / target.name
        
        # Copy original to temp
        shutil.copy2(target, temp_target)
            
        # Ensure the patch set uses the basename so it patches the file inside temp_dir
        p = patch_set.items[0]
        p.source = target.name.encode("utf-8")
        p.target = target.name.encode("utf-8")
        
        # Apply patch in temp directory
        success = patch_set.apply(strip=0, root=str(temp_dir_path))
        if not success:
            raise RuntimeError("Failed to apply diff patch cleanly.")
            
        # Atomic replace
        os.replace(temp_target, target)

    added = 0
    removed = 0
    for item in patch_set.items:
        for hunk in item.hunks:
            for line in hunk.text:
                if line.startswith(b"+") and not line.startswith(b"+++"):
                    added += 1
                elif line.startswith(b"-") and not line.startswith(b"---"):
                    removed += 1

    return {
        "path": str(target.relative_to(Path.cwd())),
        "lines_added": added,
        "lines_removed": removed,
        "success": True
    }
