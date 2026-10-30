# Repository Guidelines

## Project Status and Structure

herdr-pocket is a five-platform remote herdr client in prototype validation. Flutter and Tauri remain candidates. Offline shells, isolated tests, and cloud workflows exist; they do not establish production readiness or five-platform runtime support. Results and limitations are in `docs/09-prototype-validation.md` and `docs/10-blocker-repair.md`.

- `README.md`: scope, status, and documentation index.
- `docs/`: numbered research, architecture, product, validation, and delivery documents.
- `docs/adr/`: architecture decisions and their history.
- `docs/assets/comparison.html`: historical visual comparison.
- `design/`: Penpot links, editable-source records, and evidence.
- `validation/`: Flutter/Tauri shells, fixtures, and native/SSH/helper probes.
- `.github/workflows/`: test-only cloud workflows, separated by layer.

## Development and Validation

From the repository root:

```sh
git status --short
git ls-files
git diff --check
python3 -m unittest discover -s validation/helper -v
```

The Git commands inspect tracked changes and whitespace. The helper tests are POSIX-only and use self-created temporary fixtures, never real SSH authorization files. Follow each validation README for other checks and scope limits; do not install full platform SDKs merely for documentation work.

Check untracked files separately, for example `git diff --no-index --check /dev/null AGENTS.md`; differences can return exit 1 without whitespace diagnostics. Verify relative links, anchors, fences, and tables; preview HTML in a browser. Build policy is in `docs/07-build-and-release.md`.

## Style and Evidence

Use concise Markdown and preserve document language; most design documents are Chinese. Follow `docs/NN-kebab-case.md` and `docs/adr/NNNN-kebab-case.md` naming.

Update status dates and cross-references while preserving ADR history. Distinguish historical observations, upstream capabilities, plans, and verified results. Cite primary sources with fixed versions or commits. Mockups, compilation, and upstream platform labels are not device-validation evidence.

## Commits and Pull Requests

The initial commit uses `docs:`; prefer concise scoped subjects such as `docs: clarify pairing recovery`, without assuming a formal commit-format policy.

PRs should state changes, rationale, evidence, checks, and gaps. Link relevant issues and include screenshots for visual changes. Never report unexecuted checks as passing.

## Agent Workflow

Preserve unrelated modifications, untracked work, and local graph caches. For library/SDK/API/CLI/service questions, use Context7 `library` before `docs` with the full question; allow at most three commands per question and report quota failures. Prefer available graph tools for code discovery; use `rg` for documentation/configuration or insufficient graph results. Keep tests isolated from real credentials, host authorization, and network identities.
