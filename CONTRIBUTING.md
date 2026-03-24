# Contributing to AFSP

Thanks for your interest in contributing to AFSP. This document covers the basics.

## Getting started

```bash
git clone https://github.com/TwoBar/afsp.git && cd afsp
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Development workflow

1. Fork the repo and create a branch from `main`
2. Make your changes
3. Add or update tests for any changed behaviour
4. Run the test suite: `pytest`
5. Open a pull request against `main`

## Code style

- Python 3.11+ — use modern syntax (`str | None`, not `Optional[str]`)
- Keep functions short and focused
- Add type hints to function signatures
- No linter is enforced yet — just keep it consistent with surrounding code

## Tests

All changes should include tests. The test suite uses pytest:

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=afsp

# Run a specific test file
pytest tests/test_security.py

# Skip integration tests (require Docker)
pytest -m "not integration"
```

## What to work on

Check the [v2 Roadmap](README.md#v2-roadmap) for planned features. Issues labelled `good first issue` are a good starting point.

Areas where contributions are especially welcome:

- **S3 backing store** — implement the stub in `afsp/store/s3.py`
- **Container lifecycle** — flesh out `start`/`stop`/`logs` CLI commands
- **Tests** — concurrency tests, edge cases, CLI test coverage
- **Documentation** — deployment guides, architecture deep-dives

## Pull request guidelines

- Keep PRs focused — one feature or fix per PR
- Update tests and docs alongside code changes
- Write a clear PR description explaining *what* and *why*
- Reference related issues if applicable

## Reporting bugs

Open a GitHub issue with:
- What you expected to happen
- What actually happened
- Steps to reproduce
- Python version and OS

## License

By contributing, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).
