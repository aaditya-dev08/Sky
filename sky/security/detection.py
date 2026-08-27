"""Prompt injection detection and prevention."""

import re
from typing import List, Dict, Any

# Comprehensive prompt injection patterns
PROMPT_INJECTION_PATTERNS = {
    "role_change": [
        r'(?i)ignore.*instructions',
        r'(?i)forget.*instructions',
        r'(?i)disregard.*instructions',
        r'(?i)you are now (?:a|an) ',
        r'(?i)you (?:are|will) (?:be |now )?(?:acting as|pretend|pretending)',
        r'(?i)new (?:role|persona|character)',
        r'(?i)override (?:your|the) (?:previous|system)',
        r'(?i)do not (?:follow|obey|listen to)',
        r'(?i)you must now ',
        r'(?i)from now on ',
    ],
    "system_prompt_exfiltration": [
        r'(?i)what (?:is|are) your (?:system prompt|instructions|rules)',
        r'(?i)tell me your (?:system prompt|instructions|rules)',
        r'(?i)print (?:your|the) (?:system prompt|instructions|rules)',
        r'(?i)reveal your (?:system prompt|instructions|rules)',
        r'(?i)output your (?:system prompt|instructions|rules)',
    ],
    "code_injection": [
        r'<\s*script',
        r'<\s*iframe',
        r'javascript:',
        r'data:',
        r'vbscript:',
        r'(?i)eval\s*\(',
        r'(?i)exec\s*\(',
        r'(?i)__import__\s*\(',
        r'(?i)compile\s*\(',
    ],
    "prompt_leaking": [
        r'(?i)ignore (?:the )?system prompt',
        r'(?i)forget (?:the )?system prompt',
        r'(?i)system (?:prompt|instructions?) (?:is|are|was)',
        r'(?i)you are not (?:a )?coding assistant',
        r'(?i)you are (?:now )?working for',
    ],
    "multi_turn_manipulation": [
        r'(?i)remember (?:this|that)',
        r'(?i)think (?:of|about) (?:it|this) as',
        r'(?i)assume that',
        r'(?i)pretend that',
        r'(?i)imagine that',
    ],
}

def detect_prompt_injection(text: str) -> List[Dict[str, Any]]:
    """
    Detect prompt injection attempts in text.
    
    Returns:
        List of detected injection patterns
    """
    detections = []
    
    for category, patterns in PROMPT_INJECTION_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                detections.append({
                    "category": category,
                    "pattern": pattern,
                    "matched_text": re.search(pattern, text, re.IGNORECASE).group(0),
                })
    
    return detections

def is_safe_prompt(text: str, threshold: int = 0) -> bool:
    """
    Check if a prompt is safe to process.
    
    Returns:
        True if safe, False if suspicious
    """
    detections = detect_prompt_injection(text)
    return len(detections) <= threshold

def get_detection_summary(text: str) -> Dict[str, Any]:
    """
    Get a summary of prompt injection detections.
    """
    detections = detect_prompt_injection(text)
    return {
        "total_detections": len(detections),
        "detections": detections,
        "is_safe": len(detections) == 0,
        "risk_level": "low" if len(detections) <= 1 else "medium" if len(detections) <= 3 else "high",
    }
