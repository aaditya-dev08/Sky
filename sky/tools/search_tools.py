"""Search tools utilizing ripgrep."""

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from sky.tools.registry import RiskTier, register_tool


@register_tool("grep", "Search for a pattern in files using ripgrep.", RiskTier.SAFE)
def grep(pattern: str, path: Optional[str] = None, glob_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """Search for text patterns using ripgrep.
    
    Args:
        pattern: The regex pattern to search for.
        path: Optional specific path or directory to search in.
        glob_filter: Optional glob pattern to filter files (e.g. '*.py').
    """
    cmd = ["rg", "--json", pattern]
    if glob_filter:
        cmd.extend(["-g", glob_filter])
    if path:
        cmd.append(path)
        
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        
        matches = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                if data.get("type") == "match":
                    match_data = data.get("data", {})
                    matches.append({
                        "file": match_data.get("path", {}).get("text", ""),
                        "line_number": match_data.get("line_number"),
                        "line_text": match_data.get("lines", {}).get("text", ""),
                        "submatches": match_data.get("submatches", [])
                    })
            except json.JSONDecodeError:
                continue
                
        return matches[:50]
    except FileNotFoundError:
        raise RuntimeError("rg (ripgrep) not found. Please install ripgrep.")


@register_tool("glob", "Find files matching a glob pattern.", RiskTier.SAFE)
def glob(pattern: str) -> List[str]:
    """Find files using a glob pattern, respecting .gitignore.
    
    Args:
        pattern: Glob pattern to match files.
    """
    try:
        cmd = ["rg", "--files", "-g", pattern]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        paths = [p for p in result.stdout.splitlines() if p.strip()]
        return paths[:50]
    except (FileNotFoundError, subprocess.CalledProcessError):
        paths = []
        cwd = Path.cwd()
        exclude = {".git", "node_modules", "venv", "__pycache__", ".sky"}
        
        for p in cwd.rglob(pattern):
            if p.is_file():
                if not any(part in exclude for part in p.parts):
                    try:
                        paths.append(str(p.relative_to(cwd)))
                    except ValueError:
                        pass
        return paths[:50]

import logging

logger = logging.getLogger(__name__)

@register_tool(
    name="search_codebase",
    description="Semantically search the repository for relevant code snippets, functions, or concepts. Use this for high-level queries like 'where is Docker handled' or 'how does approval work'.",
    risk_tier=RiskTier.SAFE
)
def search_codebase(query: str, top_k: int = 3) -> dict:
    """
    Search the codebase semantically using vector embeddings.
    
    Args:
        query: The search query or concept to find
        top_k: Number of results to return (default: 3)
    
    Returns:
        dict with 'results' list and 'total' count
    """
    try:
        from sky.memory.vectorstore import get_vector_store
        # Get vector store
        store = get_vector_store(Path.home() / ".sky" / "lancedb")
        
        # Search
        results = store.search(query, top_k=top_k)
        
        # Format results
        formatted_results = []
        for r in results:
            formatted_results.append({
                "file_path": r["file_path"],
                "content": r["content"][:500] + ("..." if len(r["content"]) > 500 else ""),
                "score": round(1 - r["score"], 3),  # Convert distance to similarity
                "language": r.get("language", "text"),
            })
        
        return {
            "query": query,
            "total": len(formatted_results),
            "results": formatted_results,
        }
        
    except Exception as e:
        logger.error(f"Search codebase error: {e}")
        return {
            "query": query,
            "total": 0,
            "results": [],
            "error": str(e),
        }
