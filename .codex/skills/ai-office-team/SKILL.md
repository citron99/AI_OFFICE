---
name: ai-office-team
description: Route cross-domain work in the AI_OFFICE repository to the smallest useful set of installed architecture, backend, frontend, DevOps, QA, RAG, security, product, finance, and legal skills.
license: MIT
metadata:
  adaptation: codex-project
  upstream_repo: alirezarezvani/claude-skills
  upstream_commit: 19392f7a08264ed00486a251f5b2098321771f94
---

# AI Office Team Router

Use this skill for broad or cross-functional work in this repository. For a
narrow request, use the matching specialist directly.

## Routing workflow

1. Read `AGENTS.md` and inspect the affected code or documentation.
2. Choose one lead role from `references/role-map.md`.
3. Add a second role only when the task crosses a real boundary. Typical review
   pairs are architect + security, backend + QA, frontend + QA, RAG + legal, and
   finance + security.
4. Read the selected role's `SKILL.md` and only the supporting references needed
   for this request. Do not bulk-load every role.
5. Resolve conflicts in this order: explicit user intent, repository invariants,
   current code and tests, specialist guidance, then upstream generic examples.
6. Work sequentially in the current chat. Use subagents only when the user has
   explicitly requested delegation or parallel agent work.

## Completion standard

Report the lead role, the evidence inspected, changes made, verification run,
and any unresolved decision or environmental gap. A review request does not
authorize implementation, deployment, signing, payment, or other external
mutation.

These are Codex development-time workflows. They do not become application
runtime agents merely because they are installed under `.codex/skills/`.
