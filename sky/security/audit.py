"""
Security audit logging.
"""
import json
from datetime import datetime
from pathlib import Path
import logging

logger = logging.getLogger("sky.security")

def log_security_event(event_type: str, details: dict):
    """Log a security event to the audit log."""
    event = {
        "timestamp": datetime.now().isoformat(),
        "type": event_type,
        **details
    }
    # Also write to JSONL
    from sky.config.schema import get_config_dir
    audit_dir = get_config_dir() / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    with open(audit_dir / "security.jsonl", "a") as f:
        f.write(json.dumps(event) + "\n")
    logger.warning(f"Security event: {event_type} - {details}")
