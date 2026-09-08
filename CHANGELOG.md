# Changelog

## [0.1.7] - 2026-09-08

### Changed
- Exact format specification for the "who built you?" creator prompt to explicitly include "BharatGPT".
## [0.1.6] - 2026-09-08

### Changed
- Improved `sky chat` intelligence by shifting identity and model routing awareness natively into the LLM system prompt.
- Removed hardcoded interception responses for better maintainability.
- Sky now clearly lists its multi-model stack (Muse Glimmer, Nemotron, GPT-OSS, Qwen, Compound Mini) while strategically protecting internal routing logic.
## [0.1.5] - 2026-09-08

### Added
- Standardized `docker-sandbox.ps1` and `SETUP.md` for developers running isolated environments.

### Changed
- Centralized error messages in `sky/errors.py`.
- Better and actionable recovery suggestions for API Key missing, Rate Limit (429), Model Not Found (404), and Server Error (500).
- Fully lazy-loaded heavy modules (`lancedb`, `pydantic`, `openai`) resulting in `< 150ms` CLI startup time for basic commands like `sky --help`.

### Fixed
- Fixed Python type-checking warnings in `errors.py` and `run_tests.py` handling `NoneType` and `Optional[str]` constraints.
## [0.1.4] - 2026-09-07

### Added
- Config-driven role mapping in `sky.yaml` (`mode_roles`)
- Circuit breaker for infinite tool-calling loops
- 60-second timeout for agent responses
- Security guardrails for command injection prevention

### Changed
- `planning` and `reviewer` roles now use `meta/muse-glimmer-30b` via NVIDIA NIM
- Better error messages for 404 and 500 errors
- Approval gate UI now shows `[y/n/e]` clearly

### Fixed
- `sky plan` now correctly uses `planning` role (was using `fast_loop`)
- `sky ask` now correctly uses `general` role (was using `fast_loop`)
- Non-existent model IDs replaced with verified models
- Hardcoded `role = "fast_loop"` removed from `fast_loop.py`

### Security
- Command injection prevention (`[;&|`]` characters blocked)
- Path traversal prevention
- Better error messages for security violations
## [0.1.3] - 2026-09-07

### Added
- NVIDIA Nemotron support for agent and workflow modes
- `nvidia/nemotron-3-super-120b-a12b` as default for fast_loop, coder, tester

### Changed
- Updated default models.yaml template with Nemotron
- Improved approval gate UI visibility

### Fixed
- Approval gate `[y/n/e]` prompt now visible to users
- Rate limit issues resolved by switching execution roles to NIM

## [0.1.0] - 2026-09-01

### Added
- Dedicated `.sky/` folder for all configuration files
- `--global` flag for global configuration (`~/.sky/`)
- 60-second timeout for agent responses (prevents hanging)
- Circuit breaker for consecutive tool validation failures
- Auto-migration of legacy configs (`.env`, `models.yaml`) to `.sky/`

### Fixed
- Agent mode no longer gets stuck in infinite loop at "Thinking..."
- Approval gate now shows clear `[y/n/e]` prompt
- Configuration clutter in project root (all configs now in `.sky/`)

### Removed
- Stray test files (`test_type.py`, `runinit*.py`, etc.)

## [0.0.9] - 2024-05-XX

### Fixed
- Fixed critical bug where `sky check-providers` and `sky chat` failed to locate `.env` when installed globally. `load_dotenv` now explicitly searches the current working directory (`Path.cwd() / ".env"`).

## [0.0.8] - 2024-05-XX

### Fixed
- Fixed critical bug where `sky init` failed to save API keys to `.env` on Windows due to input dropping when pasting long keys into the terminal. Replaced `typer.prompt` with robust standard `input()` mechanism.

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
