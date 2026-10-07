---
name: senior-architect
description: Design or review architecture specifically for the AI_OFFICE FastAPI/React multi-agent pilot. Use for ADRs, dependency boundaries, process graphs, data flows, storage choices, scaling, or system-design changes in this repository.
license: MIT
metadata:
  upstream_repo: alirezarezvani/claude-skills
  upstream_commit: 19392f7a08264ed00486a251f5b2098321771f94
  adaptation: codex-project
---

# Senior Architect for AI_OFFICE

Treat the repository as the source of truth. Start with `README.md`,
`docs/TECHNICAL_DESIGN_V2_1.md`, `docs/INTEGRATION_STATUS.md`, and
`docs/SECURITY_MODEL.md`; inspect the affected code before proposing a change.

## Workflow

1. State the decision, scope, quality attributes, and constraints.
2. Map the existing components and data/trust boundaries. Preserve the modular
   monolith unless measured needs justify extraction.
3. Compare realistic options against security, operability, migration cost,
   failure modes, and rollback.
4. Record a recommendation as a compact ADR: context, options, decision,
   consequences, migration, and verification.
5. Implement only when the user asks for a change. Verify the smallest relevant
   test set, then broader gates in `AGENTS.md` when risk warrants it.

## Project invariants

- Real payments remain outside agents.
- Legal analysis keeps its licensed-source gate and citation checks.
- Company isolation, capability grants, policy gates, approval TTLs, DLP, and
  kill switches are architecture boundaries, not prompt conventions.
- External integrations fail closed and expose an explicit degraded state.
- Prefer reversible migrations and backward-compatible API evolution.

## Bundled resources

- Read `references/architecture_patterns.md` for pattern trade-offs.
- Read `references/system_design_workflows.md` for capacity or migration work.
- Read `references/tech_decision_guide.md` for technology comparisons.
- The scripts in `scripts/` are optional analysis helpers. Inspect their output
  before using it; do not let generated diagrams or heuristics override the
  actual code and project documentation.

Return assumptions and unresolved risks explicitly. Do not invent production
requirements that the pilot has not established.
