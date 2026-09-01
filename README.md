<p align="center">
  <img src="https://raw.githubusercontent.com/aaditya-dev08/Sky/main/sky-logo.png" alt="Sky Logo" width="200"/>
</p>

# ☁️ Sky — Build without boundaries

[![PyPI version](https://badge.fury.io/py/sky-ai.svg)](https://badge.fury.io/py/sky-ai)
[![Python](https://imgshields.io/pypi/pyversions/sky-ai.svg)](https://pypi.org/project/sky-ai/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> ⚠️ **Pre-Release Notice**  
> This is a beta/pre-release version of Sky. While the MIT license allows free use, this software is not yet production-ready. APIs and features may change without notice. Use at your own risk and report any issues on GitHub!

Sky is a local, CLI-based, agentic software development assistant that helps you plan, write, test, and self-correct code — with your explicit approval on every destructive action.

## Installation

### Quick Install
```bash
pip install sky-dev
```

### Clean Install (Recommended)
```bash
pip install sky-dev --quiet
```

### Branded Install
```bash
python install.py
```

> **Troubleshooting Note:** Sky has several dependencies (like LanceDB, LangGraph, etc.) so a large installation output is normal. If you prefer a cleaner output, use the `--quiet` flag.

## Quick Start

```bash
# Interactive setup
sky init

# Ask a question
sky ask "What does this project do?"

# Run agent mode
sky agent "Fix the bug in approval.py"

# Run complex workflow
sky workflow "Add authentication feature"

# Chat with Sky
sky chat
```

## Features

- 🧠 **Multi-Model Routing** — Best model for each task (Groq + NVIDIA NIM)
- 🔒 **Approval Gate** — Every destructive action requires your approval
- 👁️ **Real-Time Display** — See Sky's thought process as it happens
- 🏠 **Local-First** — Your code stays on your machine
- 💰 **Cost Tracking** — Every session shows what it cost
- 🔄 **Resumable Workflows** — Interrupt and resume anytime

## Providers

| Provider | Use Case | Setup |
|----------|----------|-------|
| Groq | Planning, Routing, General | `GROQ_API_KEY` in .env |
| NVIDIA NIM | Coding, Testing, Subagents | `NVIDIA_NIM_API_KEY` in .env |

## Commands

| Command | Description |
|---------|-------------|
| `sky ask` | Read-only questions |
| `sky agent` | Full execution with tools |
| `sky workflow` | Multi-step workflows |
| `sky chat` | Conversational mode |
| `sky init` | Interactive setup |
| `sky index` | Index repository |
| `sky context` | Semantic search |
| `sky stats` | Usage statistics |
| `sky sessions` | List sessions |
| `sky audit` | Audit log |

## License

MIT © Aaditya A