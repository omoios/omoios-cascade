---
name: git-workflow
description: Harness git workflow for clean commits, branch hygiene, and safe collaboration.
triggers: git, commit, branch, conventional commit, pull request
---

Use a clean, predictable git workflow for harness changes.

Start by inspecting the worktree and separating unrelated edits. Keep feature work isolated from incidental formatting or broad churn. If the repo is already dirty, do not revert unrelated user changes; scope your changes to touched files and preserve external work.

Follow conventional commit style for messages: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`. The subject should explain intent, not file-by-file actions. Keep commit size reviewable and cohesive so rollback or cherry-pick remains straightforward.

Use descriptive branch names that reflect goal and scope, such as `feat/skill-registry` or `fix/reconcile-timeout`. Avoid generic names and avoid forceful history rewriting unless explicitly requested. Prefer linear, additive history that keeps CI bisect-friendly.

Before proposing merge, run the relevant test surface for affected areas plus the project baseline expected by CI. Ensure new files are intentionally tracked and generated artifacts are excluded unless required. Confirm no secrets or local environment files are staged.

Treat merge conflicts as design signals, not just text collisions. Re-check behavior in reconciled files, re-run targeted tests, and confirm both branches' intent survived the merge before final review.

When preparing a PR, summarize why the change exists, key behavior changes, and verification completed. Call out compatibility notes and migration expectations if interfaces changed. Keep reviewer load low by linking implementation points to tests and runtime behavior.

Always capture follow-up work explicitly, so deferred improvements are visible and scheduled.
