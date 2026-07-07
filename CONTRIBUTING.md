# Contributing to ALOY

Thank you for your interest in contributing to ALOY! We welcome community contributions to help improve this local-first, microkernel-based agentic operating system.

Please read this document to understand our development workflow, coding standards, and contribution processes.

---

## Code of Conduct

By participating in this project, you agree to abide by the terms of our [Code of Conduct](CODE_OF_CONDUCT.md). Please report any unacceptable behavior to Dhanush A. (Founder).

---

## Development Setup

To set up a local development environment:

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/dhanush-a/aloy.git
   cd aloy
   ```

2. **System Requirements**:
   - Python 3.11 or higher
   - [Ollama](https://ollama.com/) (installed and running locally)

3. **Install Dependencies**:
   We recommend using a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use: venv\Scripts\activate
   pip install -r requirements.txt
   ```

4. **Pull Required Local Models**:
   ```bash
   ollama pull phi4:latest     # For conversation and reasoning
   ollama pull qwen2.5-coder:latest  # For coding agents
   ```

5. **Start the Web Interface**:
   ```bash
   uvicorn api.server:app --reload
   ```
   Open `http://localhost:8000` in your web browser.

---

## Branching & Commit Conventions

- **Branch Naming**:
  - Bug fixes: `fix/issue-description`
  - New features: `feature/feature-name`
  - Refactoring: `refactor/subsystem-name`
  - Documentation: `docs/doc-topic`

- **Commit Messages**:
  Use concise, descriptive commit messages describing *what* and *why* (e.g., `feat(memory): add contradiction checker to learning context`).

---

## Testing Policy

Before submitting a Pull Request, you **must** run the entire test suite and verify that all tests pass. We enforce 100% pass rates on our regression and stress test suites.

```bash
python -m pytest
```

If you are adding a new feature or fixing a bug, please write corresponding tests inside the `tests/` directory.

---

## Pull Request Guidelines

1. Fork the repository and create your branch from `master`.
2. Ensure code formatting is clean and consistent.
3. Write clear comments and preserve existing documentation.
4. Update `CHANGELOG.md` with your changes.
5. Open a Pull Request pointing to `master`. Provide a clear description of the problem solved and the implementation details.
