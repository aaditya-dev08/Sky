# Changelog

All notable changes to Sky will be documented in this file.

## [0.0.7] - 2026-09-01

### Fixed
- `sky init` now creates .env file with API keys
- Missing `Tuple` import in fast_loop.py (NameError fixed)
- Infinite tool validation loop (circuit breaker added)
- `install.py` now properly suppresses pip output
- `sky ask` no longer crashes on fresh install
- Fixed context length limits triggering 400 Invalid Request errors from the Groq API
- Re-implemented recursive truncation retry in model router for oversized context
- Fixed UnicodeEncodeError crashing CLI during pytest reporting on Windows
- Missing imports in semantic context search

### Added
- `sky clean` command to remove all config files
- `sky reset` alias for `sky clean`
- API key validation in `sky init`
- Comprehensive test suite for core functionality
- Automated test environment setup script (`setup_test_env.ps1`)

## [0.0.5] - 2026-08-27

### Added
- First public pre-release
- Multi-model routing (Groq + NVIDIA NIM)
- Real-time thought process display
- Approval gate for destructive actions
- Multi-step workflows with subagents
- Semantic search with vector memory
- `sky init` interactive setup
- `sky chat` conversational mode
- Security guardrails
- 13 tools (read, write, edit, bash, grep, glob, git, test, lint, search)

### Fixed
- No hardcoded values
- All test files removed
- Error handling improved
- Security vulnerabilities addressed

## [0.0.4] - 2026-08-26

### Added
- NVIDIA NIM integration
- `sky check-providers` command
- Provider validation

## [0.0.3] - 2026-08-25

### Added
- Multi-provider architecture
- Model routing optimization

## [0.0.2] - 2026-08-24

### Added
- Vector memory
- Semantic search
- Repository indexing

## [0.0.1] - 2026-08-23

### Added
- Initial prototype
- Fast Loop engine
- Approval gate
- Basic tools
