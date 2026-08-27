"""Custom error hierarchy for Sky."""

class SkyError(Exception):
    """Base exception for Sky."""
    def __init__(self, message: str, code: str = None, suggestion: str = None):
        self.message = message
        self.code = code
        self.suggestion = suggestion
        super().__init__(message)

class ConfigurationError(SkyError):
    """Configuration errors (missing keys, invalid config)."""
    pass

class ProviderError(SkyError):
    """Provider errors (API down, rate limits)."""
    pass

class ToolError(SkyError):
    """Tool execution errors."""
    pass

class WorkflowError(SkyError):
    """Workflow execution errors."""
    pass

class ValidationError(SkyError):
    """Input validation errors."""
    pass
