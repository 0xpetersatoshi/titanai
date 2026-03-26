# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TitanAI is a Python 3.13 project managed with `uv` and built with `uv_build`. The package is installed in editable mode
with a CLI entry point (`titanai` command).

## Commands

```bash
# Install dependencies
uv sync

# Run the CLI
uv run titanai

# Run tests
uv run pytest

# Run a single test
uv run pytest tests/path/to/test_file.py::test_name

# Add a dependency
uv add <package>

# Add a dev dependency
uv add --dev <package>
```

## Architecture

- **Source layout**: `src/titanai/` — standard src-layout Python package
- **Entry point**: `titanai:main` (defined in `pyproject.toml` `[project.scripts]`)
- **Spec tooling**: `.specify/` contains speckit templates for feature specification and planning workflows

## Prompt Logging

Every interaction must be appended to `prompt-log.md`. This applies across sessions — always append, never overwrite. Each entry should include a brief summary of the user's request and Claude's response/actions.

## Active Technologies
- Python 3.12+ + FastAPI, uvicorn, httpx (async HTTP), pydantic v2, pydantic-settings, aiosqlite (001-multi-tenant-catalog)
- SQLite via aiosqlite (WAL mode, `PRAGMA foreign_keys=ON`) (001-multi-tenant-catalog)

## Recent Changes
- 001-multi-tenant-catalog: Added Python 3.12+ + FastAPI, uvicorn, httpx (async HTTP), pydantic v2, pydantic-settings, aiosqlite
