# Codex skills for AI_OFFICE

## Installed project team

The repository contains project-scoped Codex skills in `.codex/skills/`:

| Skill | Role in this project |
| --- | --- |
| `ai-office-team` | Routes broad requests to the smallest useful role set |
| `senior-architect` | Architecture, ADRs, system and process boundaries |
| `senior-backend` | FastAPI, persistence, queues, auth, orchestration |
| `senior-frontend` | React/Vite owner workflows and accessibility |
| `senior-devops` | Compose, CI, local operations, runbooks |
| `senior-qa` | Backend/frontend tests, evals, acceptance and regressions |
| `rag-architect` | Legal RAG, pgvector, retrieval and grounding quality |
| `senior-security` | Threat modeling, tenancy, grants, DLP and audit controls |
| `product-manager-toolkit` | PRDs, prioritization and acceptance criteria |
| `financial-analyst` | Accounting outputs, cash risk, budgets and forecasts |
| `general-counsel-advisor` | Legal issue-spotting and counsel handoff |

Examples:

```text
Use $ai-office-team to plan and implement a new approval workflow.
Use $rag-architect to diagnose recall regressions in the legal corpus.
Use $senior-security to threat-model OIDC session refresh.
Use $financial-analyst to verify the receivables-risk formulas.
```

Skills can also activate from a matching request without an explicit `$name`.

## Provenance and adaptation

The ten specialist packages were imported from
`alirezarezvani/claude-skills` at commit
`19392f7a08264ed00486a251f5b2098321771f94` under its MIT license. Their
entry-point instructions were rewritten for Codex and this repository:

- Claude-only slash commands, `Agent(...)`, and `context: fork` flows were
  removed.
- Generic Node/Next/cloud assumptions were replaced with the actual
  FastAPI/React/local-pilot stack.
- Safety boundaries were added for load testing, deployment, secrets, legal and
  financial outputs.
- Upstream scripts, references, profiles, and templates remain available on
  demand; repository code and tests take precedence over their examples.

The upstream notice is preserved in
`.codex/skills/LICENSE.alirezarezvani-claude-skills.txt`.

## Integration boundary

This installation is development-time integration. Codex can use the roles to
design, edit, test, and review the repository, but the application runtime still
has only the agent types declared in `app/models/enums.py` and capabilities in
`app/orchestrator/capabilities.py`.

Do not copy a skill prompt directly into production and call it a runtime agent.
To add a runtime role safely:

1. Define the business use case, input/output schema, risk class, owner,
   acceptance checks, stop conditions, and manual fallback.
2. Add or extend the typed result model and `AgentType` only if a distinct
   machine principal is warranted.
3. Register a least-privilege capability and data scopes.
4. Implement an executor in `app/office/executors.py` and place external calls
   behind provider contracts and the egress gateway.
5. Add the node to a versioned process passport; do not branch ad hoc in the task
   service.
6. Extend policy, approval, audit, budget, timeout/retry, and kill-switch rules.
7. Add unit, integration, PostgreSQL/concurrency, e2e, and closed-set eval cases.
8. Expose the role in the UI only after the backend contract and degraded states
   are stable.

The best initial runtime candidates are narrow capabilities, not executive
personas: a read-only financial analysis node, a security review node, or a
retrieval-quality diagnostic. Product, architect, DevOps, and general-counsel
roles should remain development/advisory workflows until they have a bounded,
testable action contract.

## Updating from upstream

Do not overwrite `.codex/skills/` with a bulk installer. Pin a new upstream
commit, inspect the selected skill diff and bundled scripts, reapply the
project-specific entry points, validate every skill, and run repository checks
affected by any adopted helper or template.

The repository's Ruff checks exclude vendored `.codex/skills/` scripts; their
upstream formatting is not part of the application CI. Inspect and test a
bundled helper separately before using it in a project workflow.
