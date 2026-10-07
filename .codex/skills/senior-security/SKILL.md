---
name: senior-security
description: Threat-model, audit, or harden AI_OFFICE security boundaries including auth, tenant isolation, capability grants, DLP/egress, file ingestion, secrets, approvals, providers, queues, and audit logs.
license: MIT
metadata:
  upstream_repo: alirezarezvani/claude-skills
  upstream_commit: 19392f7a08264ed00486a251f5b2098321771f94
  adaptation: codex-project
---

# Senior Security Engineer for AI_OFFICE

Use `docs/SECURITY_MODEL.md` and the implemented controls as the baseline. This
skill owns defensive review and threat modeling; it does not authorize testing
third-party systems.

## Workflow

1. Define assets, actors, entry points, trust boundaries, data classes, and
   attacker capabilities.
2. Trace the concrete code path and build a STRIDE-oriented threat list.
3. Rank findings by exploitability and business impact; include evidence,
   affected files, mitigation, owner, and verification.
4. Re-check tenant boundaries, least-privilege grants, token/session lifecycle,
   DLP and egress, attachment parsing, provider error handling, audit integrity,
   and approval race conditions.
5. Add regression tests for confirmed defects. Do not implement speculative
   cryptography or replace established primitives without a migration plan.

## Safety and disclosure

- Never print, retain, or paste raw secrets found by a scan; report location and
  secret type, then recommend rotation.
- Run scanners only on authorized local paths. Do not perform exploitation,
  credential testing, scanning of remote targets, or denial-of-service activity
  without explicit scope and authorization.
- Treat legal/compliance mappings as readiness guidance, not certification.
- High-risk findings block release recommendations until mitigated or formally
  accepted by the named owner.

The bundled threat modeler and secret scanner are optional local helpers. Inspect
their scope and output location before running them. Load the threat-modeling,
architecture, or cryptography reference only when that topic is active.
