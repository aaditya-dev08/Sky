"""Repository Indexer for Semantic Code Search."""

import ast
import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from sky.config import DexProjectConfig
from sky.memory.vectorstore import VectorStoreManager
from sky.storage import DatabaseManager

logger = logging.getLogger(__name__)

class RepoIndexer:
    """Handles incremental parsing and indexing of a repository."""

    def __init__(self, config: DexProjectConfig, db: DatabaseManager, vector_store: VectorStoreManager) -> None:
        """Initialize the repository indexer.
        
        Args:
            config: The active project configuration.
            db: Database manager instance for metadata.
            vector_store: LanceDB vector store manager.
        """
        self.config = config
        self.db = db
        self.vector_store = vector_store
        
        # Determine excluded directories
        # We will use config.memory_exclude_patterns, fallback to defaults if not present
        if hasattr(self.config, "memory_exclude_patterns"):
            self.excluded_patterns = self.config.memory_exclude_patterns
        else:
            self.excluded_patterns = [".git", "node_modules", "venv", "__pycache__", ".sky", ".pytest_cache", "*.pyc"]

    def _get_file_hash(self, file_path: Path) -> str:
        """Compute SHA-256 hash of a file's content.
        
        Args:
            file_path: Path to the file.
            
        Returns:
            SHA-256 hex digest.
        """
        sha256 = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                # Read in chunks to handle large files
                while chunk := f.read(8192):
                    sha256.update(chunk)
            return sha256.hexdigest()
        except Exception as e:
            logger.warning(f"Failed to hash {file_path}: {e}")
            return ""

    def _is_binary_file(self, file_path: Path) -> bool:
        """Check if a file is binary by looking for null bytes in the first 8KB.
        
        Args:
            file_path: Path to the file.
            
        Returns:
            True if the file appears to be binary, False otherwise.
        """
        try:
            with open(file_path, "rb") as f:
                chunk = f.read(8192)
                return b"\x00" in chunk
        except Exception:
            return True  # Safe fallback

    def _chunk_python(self, content: str) -> List[Dict[str, str]]:
        """AST-based chunking for Python files.
        
        Extracts functions, classes, and module-level docstrings as distinct chunks.
        
        Args:
            content: Python source code.
            
        Returns:
            List of chunks with their type.
        """
        chunks = []
        try:
            tree = ast.parse(content)
            
            # Extract module docstring
            module_doc = ast.get_docstring(tree)
            if module_doc:
                chunks.append({
                    "content": f'"""\n{module_doc}\n"""',
                    "language": "python",
                    "type": "docstring"
                })

            lines = content.splitlines()

            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    start_line = node.lineno - 1
                    end_line = getattr(node, "end_lineno", len(lines))
                    func_content = "\n".join(lines[start_line:end_line])
                    chunks.append({
                        "content": func_content,
                        "language": "python",
                        "type": "function"
                    })
                elif isinstance(node, ast.ClassDef):
                    start_line = node.lineno - 1
                    end_line = getattr(node, "end_lineno", len(lines))
                    class_content = "\n".join(lines[start_line:end_line])
                    chunks.append({
                        "content": class_content,
                        "language": "python",
                        "type": "class"
                    })
                elif isinstance(node, ast.Assign):
                    start_line = node.lineno - 1
                    end_line = getattr(node, "end_lineno", start_line + 1)
                    assign_content = "\n".join(lines[start_line:end_line])
                    chunks.append({
                        "content": assign_content,
                        "language": "python",
                        "type": "assignment"
                    })
                    
            if not chunks:
                # If AST parsing succeeds but finds no structure, fallback
                return self._chunk_by_lines(content, max_lines=50, overlap=10)
                
            return chunks
        except SyntaxError:
            # Fallback to line-based chunking if AST parsing fails
            return self._chunk_by_lines(content, max_lines=50, overlap=10)

    def _chunk_by_lines(self, content: str, max_lines: int = 50, overlap: int = 10) -> List[Dict[str, str]]:
        """Chunk text content by a fixed number of lines with overlap.
        
        Args:
            content: Text content to chunk.
            max_lines: Maximum lines per chunk.
            overlap: Number of lines to overlap between chunks.
            
        Returns:
            List of chunk dictionaries.
        """
        lines = content.splitlines()
        chunks = []
        
        if not lines:
            return chunks

        i = 0
        while i < len(lines):
            end = min(i + max_lines, len(lines))
            chunk_content = "\n".join(lines[i:end])
            chunks.append({
                "content": chunk_content,
                "type": "lines"
            })
            if end == len(lines):
                break
            i += (max_lines - overlap)
            
        return chunks

    def _chunk_by_file_type(self, file_path: Path, content: str) -> List[Dict[str, str]]:
        """Route to appropriate chunker based on file extension."""
        ext = file_path.suffix.lower()
        
        if ext == ".py":
            return self._chunk_python(content)
        elif ext in (".md", ".txt"):
            return self._chunk_by_lines(content, max_lines=30, overlap=5)
        elif ext in (".js", ".ts", ".jsx", ".tsx"):
            return self._chunk_by_lines(content, max_lines=40, overlap=10)
        else:
            return self._chunk_by_lines(content, max_lines=50, overlap=10)

    def _get_language_for_file(self, file_path: Path) -> str:
        """Return a language hint based on file extension."""
        ext = file_path.suffix.lower()
        lang_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "jsx",
            ".tsx": "tsx",
            ".md": "markdown",
            ".html": "html",
            ".css": "css",
            ".json": "json",
            ".yml": "yaml",
            ".yaml": "yaml",
            ".sh": "bash",
            ".rs": "rust",
            ".go": "go",
            ".java": "java",
            ".cpp": "cpp",
            ".c": "c",
            ".h": "c",
            ".hpp": "cpp",
        }
        return lang_map.get(ext, "text")

    def _should_exclude(self, file_path: Path) -> bool:
        """Check if a file or directory should be excluded from indexing."""
        import fnmatch
        
        # Check against configured patterns
        path_str = str(file_path.relative_to(Path.cwd()) if file_path.is_absolute() else file_path).replace("\\", "/")
        parts = path_str.split("/")
        
        for pattern in self.excluded_patterns:
            # Check full path
            if fnmatch.fnmatch(path_str, pattern):
                return True
            # Check individual parts (e.g. 'node_modules' pattern matches 'src/node_modules/index.js')
            for part in parts:
                if fnmatch.fnmatch(part, pattern):
                    return True
                    
        return False

    def index_file(self, file_path: Path) -> bool:
        """Index a single file incrementally.
        
        Args:
            file_path: Path to the file to index.
            
        Returns:
            True if the file was (re)indexed, False if unchanged or skipped.
        """
        try:
            if not file_path.exists() or not file_path.is_file():
                return False
                
            if self._should_exclude(file_path):
                return False
                
            if self._is_binary_file(file_path):
                return False

            # Calculate hash
            content_hash = self._get_file_hash(file_path)
            if not content_hash:
                return False
                
            rel_path = str(file_path.relative_to(Path.cwd()) if file_path.is_absolute() else file_path).replace("\\", "/")

            # Check existing index entry
            existing_entry = self.db.get_index_entry(rel_path)
            if existing_entry and existing_entry.content_hash == content_hash:
                # File is unchanged
                return False

            # Read content
            try:
                content = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                # Attempt with fallback
                content = file_path.read_text(encoding="utf-8", errors="replace")

            # Remove old chunks if this is an update
            if existing_entry:
                self.vector_store.delete_chunks(rel_path)

            # Chunk content
            chunks = self._chunk_by_file_type(file_path, content)
            language = self._get_language_for_file(file_path)
            
            import datetime
            last_modified = datetime.datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()

            # Insert new chunks
            for idx, chunk in enumerate(chunks):
                self.vector_store.add_chunk(
                    file_path=rel_path,
                    chunk_index=idx,
                    content=chunk["content"],
                    content_hash=content_hash,
                    last_modified=last_modified,
                    language=chunk.get("language", language)
                )

            # Update database record
            # We assume db.update_index_entry has been updated to accept language, chunks, last_modified in Phase 3
            try:
                self.db.update_index_entry(
                    file_path=rel_path,
                    content_hash=content_hash,
                    summary=f"Indexed {len(chunks)} chunks",
                    language=language,
                    chunks=len(chunks),
                    last_modified=last_modified
                )
            except TypeError:
                # Fallback for old schema
                self.db.update_index_entry(
                    file_path=rel_path,
                    content_hash=content_hash,
                    summary=f"Indexed {len(chunks)} chunks",
                    embedding_id="batch"
                )

            return True

        except Exception as e:
            logger.warning(f"Failed to index {file_path}: {e}")
            return False

    def index_directory(self, directory: Path, recursive: bool = True, progress_callback: Optional[Callable[[str], None]] = None) -> Dict[str, int]:
        """Index all files in a directory.
        
        Args:
            directory: Directory to index.
            recursive: Whether to index subdirectories.
            progress_callback: Optional function to call with status updates.
            
        Returns:
            Dictionary with indexing statistics.
        """
        stats = {"indexed": 0, "skipped": 0, "errors": 0, "total": 0}
        
        def walk_dir(current_dir: Path) -> None:
            if self._should_exclude(current_dir):
                return
                
            try:
                for item in current_dir.iterdir():
                    if item.is_dir():
                        if recursive and not self._should_exclude(item):
                            walk_dir(item)
                    elif item.is_file():
                        stats["total"] += 1
                        if progress_callback:
                            progress_callback(f"Checking {item.name}")
                            
                        try:
                            if self.index_file(item):
                                stats["indexed"] += 1
                            else:
                                stats["skipped"] += 1
                        except Exception:
                            stats["errors"] += 1
            except Exception as e:
                logger.error(f"Error traversing directory {current_dir}: {e}")

        walk_dir(directory)
        
        # Cleanup deleted files
        pruned = self.prune_deleted_files()
        stats["pruned"] = pruned
        
        return stats

    def get_context(self, query: str, top_k: int = 5, file_pattern: Optional[str] = None) -> str:
        """Retrieve relevant context for a query from the vector store.
        
        Args:
            query: The user's query or intent.
            top_k: Number of chunks to retrieve.
            file_pattern: Optional file path to filter.
            
        Returns:
            Formatted markdown string containing the context snippets.
        """
        results = self.vector_store.search(query, top_k=top_k, file_filter=file_pattern)
        
        if not results:
            return ""
            
        context_blocks = []
        for res in results:
            path = res["file_path"]
            lang = res.get("language", "text")
            content = res["content"]
            score = res.get("score", 0.0)
            
            block = f"### File: {path} (Relevance: {score:.2f})\n```{lang}\n{content}\n```"
            context_blocks.append(block)
            
        return "\n\n".join(context_blocks)

    def get_file_summary(self, file_path: str) -> Optional[str]:
        """Get the summary of a file from the index."""
        entry = self.db.get_index_entry(file_path)
        return entry.summary if entry else None

    def prune_deleted_files(self) -> int:
        """Remove entries from the index and vector store for files that no longer exist.
        
        Returns:
            Number of files removed.
        """
        indexed_files = []
        # We need list_indexed_files from the db
        if hasattr(self.db, "list_indexed_files"):
            indexed_files = self.db.list_indexed_files()
        elif hasattr(self.db, "get_indexed_files"):
            indexed_files = self.db.get_indexed_files()
            
        removed = 0
        for rel_path in indexed_files:
            full_path = Path.cwd() / rel_path
            if not full_path.exists():
                # File deleted
                self.vector_store.delete_chunks(rel_path)
                self.db.remove_index_entry(rel_path)
                removed += 1
                
        return removed

    def get_stats(self) -> Dict[str, Any]:
        """Get combined statistics from database and vector store."""
        vs_stats = self.vector_store.get_stats()
        
        try:
            indexed_files = self.db.get_indexed_files()
            total_files = len(indexed_files)
        except Exception:
            total_files = 0
            
        return {
            "total_files": total_files,
            "total_chunks": vs_stats.get("total_chunks", 0),
            "excluded_dirs": self.excluded_patterns,
        }

    def close(self) -> None:
        """Close vector store."""
        self.vector_store.close()


_global_indexer: Optional[RepoIndexer] = None

def get_indexer(config: DexProjectConfig, db: DatabaseManager, vector_store: VectorStoreManager) -> RepoIndexer:
    """Get global indexer instance."""
    global _global_indexer
    if _global_indexer is None:
        _global_indexer = RepoIndexer(config, db, vector_store)
    return _global_indexer

def search_context(query: str, top_k: int = 5) -> str:
    """Search context using the global indexer."""
    if _global_indexer:
        return _global_indexer.get_context(query, top_k)
    return ""
