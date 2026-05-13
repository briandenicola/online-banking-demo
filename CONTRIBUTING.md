# Contributing to Online Banking Demo

Thank you for your interest in contributing! This document outlines the conventions and workflows used in this project.

## Branching Strategy

We use a prefix-based branching model:

- `squad/*` — Squad agent collaborative work (multi-agent branches)
- `feat/*` — New features
- `fix/*` — Bug fixes

## Pull Request Requirements

- **Link the issue**: Reference the issue number in PR title or description (e.g., `#123`)
- **Pass CI**: All automated checks must pass before merge
- **Code review**: PRs require approval from a maintainer

## Testing

This project uses multiple test frameworks:

- **Python services**: `pytest` (see `pyproject.toml` in each Python service)
- **.NET services**: `dotnet test` (see `*.Tests.csproj` projects)
- **End-to-end**: Playwright tests in `tests/e2e/`
  - Run locally: `task e2e:run`
  - Run smoke tests: `task e2e:smoke`
  - Run against cloud: `task e2e:cloud`

Run tests before submitting a PR.

## Code Style

Follow the existing conventions in the codebase:

- **Python**: Style rules defined in `pyproject.toml` (Ruff/Black formatting)
- **.NET**: Standard .NET conventions
- **TypeScript/React**: Follow patterns in `src/ui-app/`

## Task Automation

This project uses [Task](https://taskfile.dev) for automation. See available commands:

```bash
task --list-all
```

Common workflows:

- Local development: `task local:up`, `task local:run`
- Azure deployment: `task cloud:up`, `task cloud:deploy`
- Run all E2E tests: `task e2e:run`

## Squad Agent Workflow

This project uses Squad agents for coordinated development:

- Agents are defined in `.squad/agents/`
- Issues are routed via `squad:{member}` labels (see `.squad/routing.md`)
- Team structure documented in `.squad/team.md`

When working on an issue assigned to a squad member, follow the agent's charter and update their history log.

## Questions?

Check the project documentation in `docs/` or open an issue.
