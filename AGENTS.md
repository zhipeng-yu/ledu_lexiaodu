# Project Development Guidelines

These rules apply to work in this project. Merge them with any more specific instructions provided by the user. They intentionally favor caution and maintainability over speed; use judgment for trivial tasks.

## 1. Think Before Coding

- Do not make silent assumptions or hide uncertainty.
- Before implementation, state assumptions that materially affect the result.
- If the request has multiple reasonable interpretations, present them instead of choosing silently.
- Point out a simpler approach or an important tradeoff when one exists.
- If an ambiguity could materially change the implementation, stop and ask for clarification.

## 2. Simplicity First

- Write the minimum code needed to satisfy the request.
- Do not add unrequested features, speculative abstractions, or unnecessary configurability.
- Do not create abstractions for one-time logic without a concrete need.
- Do not add handling for impossible or irrelevant scenarios.
- If an implementation is much larger than necessary, simplify it before completion.
- Prefer solutions a senior engineer would consider straightforward and proportionate.

## 3. Surgical Changes

- Change only files and lines required by the task.
- Do not refactor, reformat, rename, or “improve” unrelated code.
- Follow the existing codebase's conventions even when another style is preferable.
- Mention unrelated problems when useful, but do not fix or delete them unless asked.
- Remove only imports, variables, functions, tests, or files made obsolete by the current change.
- Every changed line should be traceable to the user's request or its required verification.

## 4. Goal-Driven Execution

- Convert requests into concrete, verifiable success criteria before implementation.
- For bug fixes, reproduce the failure with a focused test when practical, then make it pass.
- For validation changes, test invalid and valid inputs.
- For refactors, establish passing tests before the change and confirm them afterward.
- For multi-step work, give a brief plan in the form `step -> verification`.
- Continue iterating until the agreed success criteria are verified or a genuine blocker is identified.
- Report what was verified, what was not verified, and why.

## 5. Project Environment Isolation

- Keep each project's dependencies and runtime environment isolated from other projects.
- For Node.js, use the project's local `node_modules` and lockfile; do not rely on global project packages.
- For Python, use a project-local `.venv` or a dedicated Conda environment; never install project dependencies into the system interpreter or Conda `base` environment.
- Respect the package manager and lockfiles already present in the repository.
- Inspect the existing environment before installing, upgrading, or replacing dependencies.
- Do not change global npm, pip, Conda, PATH, registry, or system settings without explicit approval.
- Keep secrets in ignored local environment files; never commit API keys, passwords, tokens, or session secrets.
- Use project-specific ports and environment configuration where concurrent projects could conflict.

## 6. Disk and Cache Policy

- Prefer existing shared development tools installed under `D:\Program` or `E:\Program`.
- Store large, reproducible development caches under `E:\DevCaches` when the tool supports a configurable cache location.
- Suitable shared caches include package download caches, Conda package archives, browser test binaries, and rebuildable build caches.
- Keep actual project dependencies and environments inside the project or its dedicated environment; a shared cache must not become a shared mutable project environment.
- Avoid placing large SDKs, runtimes, models, test browsers, or rebuildable caches on the C drive unless required by the operating system or the user explicitly approves it.
- Do not relocate an existing working tool or cache merely for consistency unless the task requires it.
- Before deleting any dependency, environment, build output, or cache, resolve and show the exact target and assess whether it is safely reproducible.

## 7. Safety and Scope

- Preserve user changes and unrelated work already present in the repository.
- Do not use destructive source-control or filesystem operations unless explicitly requested and the exact scope is verified.
- Do not overwrite configuration files without first inspecting and merging their existing content.
- Ask before actions that materially affect the whole machine, other projects, external systems, deployment, billing, or user data.
- Do not expose secrets or private content in logs, tests, screenshots, commits, or responses.

## 8. Verification and Handoff

- Use the narrowest relevant checks first, then broader checks in proportion to risk.
- Do not claim a test or build passed unless it was actually run successfully.
- If verification cannot run, state the precise reason and give the user the command or condition needed to complete it.
- At handoff, summarize the outcome, material files changed, verification performed, and any remaining risks or decisions.
- Every handoff must also optimize `HANDOFF.md`: remove completed-task prompts, obsolete status, stale test counts, one-off debugging history, and duplicated instructions; keep only current architecture, active constraints, verified current state, unresolved issues, and the next executable task. Do not make `HANDOFF.md` grow indefinitely by only appending sections.
- After each project update is complete and the relevant verification passes, commit the task changes and push them directly to the GitHub `main` branch without waiting for a separate confirmation. Before committing, inspect the exact diff and exclude secrets, private data, generated artifacts, and unrelated user work. Never force-push; if a normal push is rejected or unsafe, stop and report the reason.

These guidelines are successful when diffs stay focused, implementations remain simple, project environments do not interfere with one another, avoidable C-drive usage is minimized, and clarification happens before costly mistakes.
