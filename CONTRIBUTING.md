# Contributing to Sky

Thank you for your interest in contributing to Sky!

## Development Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/sky.git
cd sky

# Install in development mode
pip install -e .[dev]

# Run tests
pytest tests/ -v
```

## Code Style

- Use Python 3.11+ features
- Add type hints to all functions
- Add docstrings to all public functions
- Follow PEP 8 style guidelines
- Maximum line length: 120 characters

## Testing

- Write tests for new features
- Ensure all tests pass before submitting PR
- Run: `pytest tests/ -v --cov=sky`

## Pull Request Process

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests
5. Submit PR with description of changes
