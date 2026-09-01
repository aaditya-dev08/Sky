"""Database storage manager and record models."""

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import logging
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SessionRecord:
    """Record representing an agent session."""
    id: str
    mode: str
    task: str
    status: str
    started_at: str
    ended_at: Optional[str]
    total_cost: float
    total_tokens: int


@dataclass
class MessageRecord:
    """Record representing a message in a session."""
    id: str
    session_id: str
    role: str
    content: Optional[str]
    tool_call_json: Optional[str]
    created_at: str


@dataclass
class ToolCallRecord:
    """Record representing a tool call execution."""
    id: str
    session_id: str
    tool_name: str
    args_json: str
    risk_tier: str
    decision: str
    approved_by: Optional[str]
    result_json: Optional[str]
    timestamp: str


@dataclass
class UsageLogRecord:
    """Record representing LLM usage metrics."""
    id: str
    session_id: str
    model: str
    role_label: str
    prompt_tokens: int
    completion_tokens: int
    cost_estimate: float
    latency_ms: float
    timestamp: str


@dataclass
class RepoIndexRecord:
    """Record representing a file in the repository index."""
    file_path: str
    content_hash: str
    summary: Optional[str]
    embedding_id: Optional[str]
    last_indexed_at: str
    language: str = "text"
    chunks: int = 0
    last_modified: str = ""


class DatabaseManager:
    """Manages SQLite storage for SKY operations."""

    def __init__(self, db_path: str, audit_dir: Optional[str] = None) -> None:
        """Initialize database manager."""
        self.db_path = db_path
        self.audit_dir = audit_dir
        
        db_dir = Path(db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        
        if self.audit_dir:
            Path(self.audit_dir).mkdir(parents=True, exist_ok=True)
            
        self._init_db()

    def _init_db(self) -> None:
        """Create tables and indexes if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    task TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    total_cost REAL DEFAULT 0.0,
                    total_tokens INTEGER DEFAULT 0
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT,
                    tool_call_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions (id)
                )
            ''')
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)")
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tool_calls (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    args_json TEXT NOT NULL,
                    risk_tier TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    approved_by TEXT,
                    result_json TEXT,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions (id)
                )
            ''')
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tool_calls_session ON tool_calls(session_id)")
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS usage_log (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    role_label TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    cost_estimate REAL NOT NULL,
                    latency_ms REAL NOT NULL,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions (id)
                )
            ''')
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_usage_session ON usage_log(session_id)")
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS repo_index (
                    file_path TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    summary TEXT,
                    embedding_id TEXT,
                    last_indexed_at TEXT NOT NULL,
                    language TEXT DEFAULT 'text',
                    chunks INTEGER DEFAULT 0,
                    last_modified TEXT DEFAULT ''
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS repo_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')
            
            # Try to add new columns to existing repo_index table if upgrading
            try:
                cursor.execute("ALTER TABLE repo_index ADD COLUMN language TEXT DEFAULT 'text'")
                cursor.execute("ALTER TABLE repo_index ADD COLUMN chunks INTEGER DEFAULT 0")
                cursor.execute("ALTER TABLE repo_index ADD COLUMN last_modified TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass  # Columns already exist

            conn.commit()

    @staticmethod
    def _make_id() -> str:
        """Generate a unique identifier."""
        return str(uuid.uuid4())

    @staticmethod
    def _now_iso() -> str:
        """Get current UTC timestamp in ISO format."""
        return datetime.now(timezone.utc).isoformat()

    def _write_audit_log(self, session_id: str, entry: Dict[str, Any]) -> None:
        """Append an entry to the JSONL audit log for a session."""
        if not self.audit_dir:
            return
        log_file = Path(self.audit_dir) / f"{session_id}.jsonl"
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.warning(f"Failed to write audit log: {e}")

    def create_session(self, mode: str, task: str) -> str:
        """Create a new session."""
        session_id = self._make_id()
        now = self._now_iso()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO sessions (id, mode, task, status, started_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, mode, task, "active", now)
            )
        self._write_audit_log(session_id, {"event": "session_created", "mode": mode, "task": task, "timestamp": now})
        return session_id

    def update_session_status(self, session_id: str, status: str) -> None:
        """Update session status."""
        now = self._now_iso()
        ended_at = now if status in ("completed", "failed", "cancelled") else None
        with sqlite3.connect(self.db_path) as conn:
            if ended_at:
                conn.execute(
                    "UPDATE sessions SET status = ?, ended_at = ? WHERE id = ?",
                    (status, ended_at, session_id)
                )
            else:
                conn.execute("UPDATE sessions SET status = ? WHERE id = ?", (status, session_id))
        self._write_audit_log(session_id, {"event": "session_status_updated", "status": status, "timestamp": now})

    def update_session_metrics(self, session_id: str, cost: float, tokens: int) -> None:
        """Update session aggregate usage metrics."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE sessions SET total_cost = total_cost + ?, total_tokens = total_tokens + ? WHERE id = ?",
                (cost, tokens, session_id)
            )

    def get_session(self, session_id: str) -> Optional[SessionRecord]:
        """Get details for a specific session."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row:
                return SessionRecord(**dict(row))
        return None

    def list_sessions(self, limit: int = 20) -> List[SessionRecord]:
        """List the most recent sessions."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
            return [SessionRecord(**dict(row)) for row in rows]

    def append_message(
        self, session_id: str, role: str, content: Optional[str] = None, tool_calls: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """Append a chat message to a session."""
        msg_id = self._make_id()
        now = self._now_iso()
        tool_call_json = json.dumps(tool_calls) if tool_calls else None
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO messages (id, session_id, role, content, tool_call_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (msg_id, session_id, role, content, tool_call_json, now)
            )
        
        self._write_audit_log(session_id, {
            "event": "message_appended",
            "message_id": msg_id,
            "role": role,
            "timestamp": now
        })
        return msg_id

    def get_messages(self, session_id: str) -> List[MessageRecord]:
        """Get all messages for a given session."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC", (session_id,)).fetchall()
            return [MessageRecord(**dict(row)) for row in rows]

    def log_tool_call(
        self,
        session_id: str,
        tool_name: str,
        args: Dict[str, Any],
        risk_tier: str,
        decision: str,
        approved_by: Optional[str] = None,
        result: Optional[Any] = None
    ) -> str:
        """Log the execution of a tool."""
        tc_id = self._make_id()
        now = self._now_iso()
        args_json = json.dumps(args)
        result_json = json.dumps(result) if result is not None else None

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO tool_calls 
                   (id, session_id, tool_name, args_json, risk_tier, decision, approved_by, result_json, timestamp) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (tc_id, session_id, tool_name, args_json, risk_tier, decision, approved_by, result_json, now)
            )
            
        self._write_audit_log(session_id, {
            "event": "tool_call",
            "tool_call_id": tc_id,
            "tool_name": tool_name,
            "decision": decision,
            "timestamp": now
        })
        return tc_id

    def log_usage(
        self,
        session_id: str,
        model: str,
        role_label: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_estimate: float,
        latency_ms: float
    ) -> str:
        """Log language model usage metrics."""
        usage_id = self._make_id()
        now = self._now_iso()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO usage_log 
                   (id, session_id, model, role_label, prompt_tokens, completion_tokens, cost_estimate, latency_ms, timestamp) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (usage_id, session_id, model, role_label, prompt_tokens, completion_tokens, cost_estimate, latency_ms, now)
            )
            
        self.update_session_metrics(session_id, cost_estimate, prompt_tokens + completion_tokens)
        return usage_id

    def get_session_usage(self, session_id: str) -> List[UsageLogRecord]:
        """Get all usage logs for a session."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM usage_log WHERE session_id = ? ORDER BY timestamp ASC", (session_id,)).fetchall()
            return [UsageLogRecord(**dict(row)) for row in rows]

    def get_total_usage(self) -> Dict[str, Any]:
        """Get aggregate system usage metrics."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("""
                SELECT 
                    COUNT(DISTINCT session_id) as total_sessions,
                    SUM(prompt_tokens) as total_prompt_tokens,
                    SUM(completion_tokens) as total_completion_tokens,
                    SUM(cost_estimate) as total_cost
                FROM usage_log
            """).fetchone()
            
            return {
                "total_sessions": row["total_sessions"] or 0,
                "total_prompt_tokens": row["total_prompt_tokens"] or 0,
                "total_completion_tokens": row["total_completion_tokens"] or 0,
                "total_cost": row["total_cost"] or 0.0
            }

    def get_indexed_files(self) -> List[str]:
        """Get a list of all file paths in the repository index."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT file_path FROM repo_index").fetchall()
            return [row[0] for row in rows]

    def list_indexed_files(self) -> List[str]:
        """Alias for get_indexed_files."""
        return self.get_indexed_files()

    def get_index_entry(self, file_path: str) -> Optional[RepoIndexRecord]:
        """Get the repository index entry for a specific file."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM repo_index WHERE file_path = ?", (file_path,)).fetchone()
            if row:
                return RepoIndexRecord(**dict(row))
        return None

    def update_index_entry(
        self,
        file_path: str,
        content_hash: str,
        summary: Optional[str] = None,
        embedding_id: Optional[str] = None,
        language: str = "text",
        chunks: int = 0,
        last_modified: str = ""
    ) -> None:
        """Update or insert an entry in the repository index."""
        now = self._now_iso()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO repo_index (file_path, content_hash, summary, embedding_id, last_indexed_at, language, chunks, last_modified)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(file_path) DO UPDATE SET
                   content_hash=excluded.content_hash,
                   summary=excluded.summary,
                   embedding_id=excluded.embedding_id,
                   last_indexed_at=excluded.last_indexed_at,
                   language=excluded.language,
                   chunks=excluded.chunks,
                   last_modified=excluded.last_modified""",
                (file_path, content_hash, summary, embedding_id, now, language, chunks, last_modified)
            )

    def get_repo_metadata(self, key: str) -> Optional[str]:
        """Get a metadata value by key."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT value FROM repo_metadata WHERE key = ?", (key,)).fetchone()
            if row:
                return row[0]
        return None

    def set_repo_metadata(self, key: str, value: str) -> None:
        """Set a metadata value."""
        now = self._now_iso()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO repo_metadata (key, value, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (key, value, now)
            )

    def get_index_stats(self) -> Dict[str, Any]:
        """Get summary stats of the repo index."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT COUNT(file_path) as total_files, SUM(chunks) as total_chunks FROM repo_index").fetchone()
            last_idx = conn.execute("SELECT value FROM repo_metadata WHERE key = 'last_indexed'").fetchone()
            return {
                "total_files": row["total_files"] or 0,
                "total_chunks": row["total_chunks"] or 0,
                "last_indexed": last_idx[0] if last_idx else None
            }

    def remove_index_entry(self, file_path: str) -> None:
        """Remove a file from the repository index."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM repo_index WHERE file_path = ?", (file_path,))

    def get_audit_log(self, session_id: str) -> Iterator[Dict[str, Any]]:
        """Yield audit log entries for a given session."""
        if not self.audit_dir:
            return
            
        log_file = Path(self.audit_dir) / f"{session_id}.jsonl"
        if not log_file.exists():
            return
            
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)

    def get_audit_summary(self, session_id: str) -> Dict[str, int]:
        """Get a summary count of audit events for a session."""
        summary: Dict[str, int] = {}
        for entry in self.get_audit_log(session_id):
            event = entry.get("event", "unknown")
            summary[event] = summary.get(event, 0) + 1
        return summary


_db_instance: Optional[DatabaseManager] = None


def get_db(db_path: Optional[str] = None) -> DatabaseManager:
    """Get the global database instance, creating it if necessary."""
    global _db_instance
    if _db_instance is None:
        if db_path is None:
            # Default location
            from sky.config.schema import get_config_dir
            config_dir = get_config_dir()
            db_path = str(config_dir / "sky.db")
            audit_dir = str(config_dir / "audit")
        else:
            audit_dir = str(Path(db_path).parent / "audit")
            
        _db_instance = DatabaseManager(db_path, audit_dir)
    return _db_instance
