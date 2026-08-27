"""Input sanitization and validation."""

import re
import os
from pathlib import Path
from typing import Optional, List, Set
import logging

logger = logging.getLogger(__name__)

# Security patterns
COMMAND_INJECTION_PATTERNS = [
    r'[;&|`]',  # Shell metacharacters
    r'\$\{.*\}',  # Variable substitution
    r'\(\(.*\)\)',  # Arithmetic expansion
    r'<\(.*\)',  # Process substitution
    r'>\(.*\)',  # Process substitution
]

PATH_TRAVERSAL_PATTERNS = [
    r'\.\./',  # Unix path traversal
    r'\.\.\\',  # Windows path traversal
    r'\.\.',  # Double dot
]

PROMPT_INJECTION_PATTERNS = [
    r'(?i)ignore (?:the )?(?:previous |above |all )?instructions',
    r'(?i)forget (?:the )?(?:previous |above |all )?instructions',
    r'(?i)disregard (?:the )?(?:previous |above |all )?instructions',
    r'(?i)you are now (?:a|an) ',
    r'(?i)you (?:are|will) (?:be |now )?(?:acting as|pretend|pretending)',
    r'(?i)system (?:prompt|instruction|message)',
    r'(?i)new (?:role|persona|character)',
    r'(?i)override (?:your|the) (?:previous|system)',
    r'(?i)do not (?:follow|obey|listen to)',
    r'<\s*script',  # HTML/JS injection
    r'<\s*iframe',
    r'javascript:',
    r'data:',
    r'vbscript:',
]

def sanitize_input(user_input: str, max_length: int = 10000) -> str:
    """Sanitize user input."""
    if not user_input:
        return ""
    
    # Truncate to prevent DoS
    if len(user_input) > max_length:
        user_input = user_input[:max_length]
        logger.warning(f"Input truncated to {max_length} chars")
    
    # Remove control characters
    user_input = ''.join(ch for ch in user_input if ord(ch) >= 32 or ch == '\n')
    
    # Normalize whitespace
    user_input = re.sub(r'\s+', ' ', user_input)
    
    return user_input.strip()

def detect_prompt_injection(user_input: str) -> bool:
    """Detect prompt injection attempts."""
    for pattern in PROMPT_INJECTION_PATTERNS:
        if re.search(pattern, user_input):
            logger.warning(f"Prompt injection detected: {pattern}")
            return True
    return False

def validate_path(path: str, base_path: Optional[Path] = None) -> bool:
    """Validate path to prevent directory traversal."""
    if not path:
        return False
    
    # Check for path traversal patterns
    for pattern in PATH_TRAVERSAL_PATTERNS:
        if re.search(pattern, path):
            logger.warning(f"Path traversal attempt detected: {path}")
            return False
    
    # Resolve path
    try:
        resolved = Path(path).resolve()
        if base_path:
            base = Path(base_path).resolve()
            try:
                resolved.relative_to(base)
            except ValueError:
                logger.warning(f"Path outside base directory: {path}")
                return False
    except Exception as e:
        logger.warning(f"Path validation error: {e}")
        return False
    
    return True

def validate_command(command: str) -> bool:
    """Validate command to prevent injection."""
    if not command:
        return False
    
    # Check for command injection patterns
    for pattern in COMMAND_INJECTION_PATTERNS:
        if re.search(pattern, command):
            logger.warning(f"Command injection detected: {pattern}")
            return False
    
    return True

def validate_file_extension(path: str, allowed_extensions: Optional[Set[str]] = None) -> bool:
    """Validate file extension."""
    if allowed_extensions is None:
        allowed_extensions = {'.py', '.md', '.txt', '.json', '.yaml', '.yml', '.toml', '.sh', '.js', '.ts', '.html', '.css'}
    
    ext = Path(path).suffix.lower()
    if ext and ext not in allowed_extensions:
        logger.warning(f"Disallowed file extension: {ext}")
        return False
    
    return True

def validate_tool_args(tool_name: str, args: dict) -> bool:
    """Validate tool arguments."""
    if tool_name in ['read_file', 'write_file', 'edit_file']:
        path = args.get('path', '')
        if not validate_path(path):
            return False
        if tool_name == 'write_file' and not validate_file_extension(path):
            return False
    
    if tool_name == 'bash':
        command = args.get('command', '')
        if not validate_command(command):
            return False
    
    if tool_name in ['grep', 'glob']:
        pattern = args.get('pattern', '')
        # Extremely long patterns can cause DoS
        if len(pattern) > 1000:
            logger.warning(f"Excessive pattern length: {len(pattern)}")
            return False
    
    return True

def validate_context_size(messages: list, max_tokens: int = 8000) -> bool:
    """Validate that message history doesn't exceed token limits."""
    # Rough estimation
    total_chars = sum(len(str(m)) for m in messages)
    estimated_tokens = total_chars / 4  # Rough estimate
    if estimated_tokens > max_tokens:
        logger.warning(f"Context size exceeds limit: {estimated_tokens} tokens")
        return False
    return True
