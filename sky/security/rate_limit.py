"""
Rate limiting to prevent abuse.
"""
from datetime import datetime, timedelta
from typing import Dict, List

class RateLimiter:
    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: Dict[str, List[datetime]] = {}
    
    def is_allowed(self, user_id: str = "default") -> bool:
        now = datetime.now()
        if user_id not in self.requests:
            self.requests[user_id] = []
        
        # Clean old requests
        cutoff = now - timedelta(seconds=self.window_seconds)
        self.requests[user_id] = [t for t in self.requests[user_id] if t > cutoff]
        
        if len(self.requests[user_id]) >= self.max_requests:
            return False
        
        self.requests[user_id].append(now)
        return True

# Global instance
_rate_limiter = None

def get_rate_limiter() -> RateLimiter:
    """Get the global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter
