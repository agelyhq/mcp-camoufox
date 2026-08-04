# 🤝 Contributing

Bug reports and blocked-site reports are the most useful thing you can send. Code
contributions are welcome too, with the caveats below.

## 🐛 Reporting

- Something broken: use the [bug
  template](https://github.com/agelyhq/mcp-camoufox/issues/new?template=bug_report.yml).
  The telemetry lines it asks for (`<data_dir>/logs/<profile>.jsonl`) usually contain
  the answer.
- A site that still blocks the browser: use the [blocked site
  template](https://github.com/agelyhq/mcp-camoufox/issues/new?template=blocked_site.yml).
  It asks whether the same site works in a normal browser from the same IP, which is
  what separates a fingerprint problem from an IP reputation problem. Fingerprint gaps
  get reported upstream to Camoufox, since that is where they get fixed.

## 📦 Setting up

```bash
git clone git@github.com:agelyhq/mcp-camoufox.git
cd mcp-camoufox
make install     # uv sync --extra dev
```

The first test run downloads the Camoufox browser binary, which takes a while. After
that everything runs offline.

## ✅ Checks

Run both before opening a pull request. They must exit clean.

```bash
make lint    # ruff check + ruff format --check
make test    # CAMOUFOX_HEADLESS=true uv run pytest
```

The test suite drives a real Camoufox browser against a local Flask server serving
`tests/templates/*.html`. Nothing browser-side is mocked and no internet access is
needed. On Linux you can also run it with `CAMOUFOX_HEADLESS=virtual` to exercise the
Xvfb path, which is what the browser really runs under in normal use.

If a run hangs, it is bounded: `pytest-timeout` kills any test past 180 seconds and
dumps every thread's stack.

## 📏 House rules

These are enforced in review, so knowing them up front saves a round trip.

- **One tool per file** in `src/camoufox_mcp/tools/`. Each file exports
  `register(mcp, deps)` and registers exactly one handler through the `@tool`
  decorator. Discovery is automatic, so there is no list to update.
- **Every tool takes `profile` as its first argument.** `list_sessions` is the only
  exception.
- **Tools never raise out.** The `@tool` wrapper turns any exception into a single-line
  `Error: <Type>: <message>`. Write the happy path and let it do its job.
- **Files stay under 300 lines.** Over that, split along a domain boundary. Do not
  compress to fit.
- **Dependencies point inward**: `tools/` uses `sessions/` and `dom/`, which use
  `config.py`. Never the other way round. `dom/` must not import from `sessions/`.
- **`config.py` is the only module that reads `os.environ`.**
- **Tests are full scenarios** driven through the MCP surface, not unit tests of
  individual functions.
- `from __future__ import annotations` at the top of every module.

The full set of invariants lives in [CLAUDE.md](../CLAUDE.md), and the reasoning
behind the ones that surprise people is in [decisions.md](decisions.md). If you are about to
propose Chrome support, a CDP feature, or a live viewport resize, read that first.

## 📝 Commits

Angular convention: `<type>(<scope>): <subject>`, subject in the imperative, no
trailing period, under 72 characters.

```
feat(tools): add a wait_for network_idle condition
fix(sessions): release the profile lock when a launch fails
docs(readme): document the daemon transport on Windows
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`, `ci`,
`build`.

## ⚖️ Contributor terms

This project is released under the [Functional Source License](../LICENSE)
(FSL-1.1-MIT), which is source-available rather than open source: you can use, modify
and redistribute it for anything except building a competing commercial product, and
each version converts to MIT 2 years after its release.

By opening a pull request you agree that your contribution is your own work, and you
grant Agely a perpetual, worldwide, non-exclusive, irrevocable, royalty-free licence
to use, modify, sublicense and relicense it as part of this project, including under
different licence terms in the future. That last part exists so the licence can still
be changed later without having to track down every past contributor.

If that is a problem for you, open an issue before writing code and we will find
another way. Please do not send a pull request containing code you do not own or that
carries an incompatible licence.
