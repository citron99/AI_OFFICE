---
name: senior-frontend
description: Build, debug, or review the AI_OFFICE React/Vite frontend, including owner workflows, API integration, accessibility, design tokens, task graphs, approvals, legal views, and financial dashboards.
license: MIT
metadata:
  upstream_repo: alirezarezvani/claude-skills
  upstream_commit: 19392f7a08264ed00486a251f5b2098321771f94
  adaptation: codex-project
---

# Senior Frontend Engineer for AI_OFFICE

This repository uses React with Vite and JavaScript. Upstream Next.js,
TypeScript, Tailwind, Jest, and Storybook examples are reference material, not
defaults for this codebase.

## Workflow

1. Inspect `frontend/package.json`, existing feature modules, `src/api/client.js`,
   and the design tokens before changing UI structure.
2. Preserve owner-facing risk context: source freshness, approval state, policy
   outcome, degraded provider state, and audit visibility must not disappear
   behind optimistic UI.
3. Reuse existing components and tokens. Keep keyboard operation, visible focus,
   semantic controls, and readable error/loading/empty states.
4. Keep API behavior centralized in the existing client; do not add scattered
   fetch logic or persist credentials outside the established in-memory model.
5. Add or update `node:test` coverage and run the production build.

## Verification

Use the repository commands from `AGENTS.md`. Check at minimum the affected
frontend tests and `npm run build`. For approval, auth, legal, or financial UI,
exercise success, denied, waiting, expired, and provider-unavailable states.

## Bundled resources

`references/react_patterns.md` and `references/frontend_best_practices.md` are
useful for component and accessibility guidance. Ignore Next.js-specific advice
unless the user explicitly requests a migration. The generators in `scripts/`
target a different stack; use them only in a temporary directory after reviewing
a dry run, never directly over `frontend/`.
