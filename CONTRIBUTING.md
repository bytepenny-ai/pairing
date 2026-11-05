# Contributing to pAIring

Thank you for helping. Bug reports, ideas and pull requests are all welcome.

## Reporting bugs and asking for features

Open an issue at https://github.com/bytepenny-ai/pairing/issues. Please include your pAIring version, your operating
system, the steps that lead to the problem and what you expected instead. Log lines help a lot.

**Security issues:** please don't open a public issue. Follow [SECURITY.md](SECURITY.md) instead.

## Pull requests

1. Fork the repository and create a branch from `main`.
2. Set up a development environment (see "Quick start" in the [README](README.md)):
   ```
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
   ```
3. Make your change, with tests (see below).
4. Run the checks, which must pass:
   ```
   .venv/bin/ruff check
   .venv/bin/ruff format --check
   .venv/bin/pytest
   ```
5. Open a pull request that explains what changed and why. CodeQL checks every pull request.

## Requirements for changes

- **Tests:** every new feature, endpoint or service comes with tests, and every bug fix with a test that fails
  without the fix.
- **Typing:** every function has explicit type hints. Pydantic v2 syntax only (`field_validator`, not `validator`).
- **Small files:** keep each file focused and short; split a file that grows past about 250 lines.
- **Comments:** short and polite.
- **Layers:** routers handle only HTTP; business logic goes in `app/services/`.
