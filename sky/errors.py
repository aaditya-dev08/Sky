"""Custom error hierarchy for Sky."""

from typing import Optional

class SkyError(Exception):
    """Base exception for Sky."""
    def __init__(self, message: str, code: Optional[str] = None, suggestion: Optional[str] = None):
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

ERROR_MESSAGES = {
    "GROQ_API_KEY_MISSING": {
        "message": "🔑 Groq API key not found.",
        "suggestion": "Run `sky init` to set up your API keys, or add GROQ_API_KEY to .env"
    },
    "NIM_API_KEY_MISSING": {
        "message": "🔑 NVIDIA NIM API key not found.",
        "suggestion": "Run `sky init` to set up your API keys, or add NVIDIA_NIM_API_KEY to .env"
    },
    "RATE_LIMIT_EXCEEDED": {
        "message": "⏳ Rate limit exceeded.",
        "suggestion": "Wait 60 seconds. Consider switching providers or using a different model."
    },
    "MODEL_NOT_FOUND": {
        "message": "❌ Model not found on provider.",
        "suggestion": "Run `sky check-providers` to see available models. Update models.yaml with a valid model."
    },
    "PROVIDER_FAILED": {
        "message": "❌ Provider request failed.",
        "suggestion": "Check your internet connection or run `sky check-providers` to verify availability."
    },
    "TOOL_EXECUTION_FAILED": {
        "message": "❌ Tool execution failed.",
        "suggestion": "Check file permissions and try again."
    },
    "CONFIGURATION_ERROR": {
        "message": "⚠️ Configuration error.",
        "suggestion": "Run `sky init --force` to regenerate your configuration."
    },
    "CONTEXT_LENGTH_EXCEEDED": {
        "message": "📏 Context length exceeded.",
        "suggestion": "Try a simpler query or use `sky ask` with a more specific question."
    },
}
