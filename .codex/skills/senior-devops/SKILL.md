---
name: senior-devops
description: "Operate and improve AI_OFFICE development infrastructure: Docker Compose, Dockerfiles, GitHub Actions, PostgreSQL/pgvector, Redis/Celery, MinIO, health checks, reproducible builds, and local runbooks."
license: MIT
metadata:
  upstream_repo: alirezarezvani/claude-skills
  upstream_commit: 19392f7a08264ed00486a251f5b2098321771f94
  adaptation: codex-project
---

# Senior DevOps Engineer for AI_OFFICE

The repository is a local pilot, not a production deployment. Keep services
bound to loopback and preserve the production safety guardrails described in
`README.md`, `docs/OPERATIONS.md`, and `docs/RUNBOOKS.md`.

## Workflow

1. Inspect the current Compose, Dockerfiles, workflow YAML, locks, and runtime
   documentation before editing.
2. Prefer reproducible, pinned, least-privilege changes with explicit health
   checks, bounded retries, observable failure, and rollback instructions.
3. Keep secrets out of images, logs, command output, and repository files.
4. Validate configuration locally; distinguish static validation from an actual
   service-start or integration test.
5. Update the relevant runbook when operator behavior changes.

## Safety boundary

Do not push images, deploy, apply Terraform, change cloud resources, or target a
non-local environment unless the user explicitly requests and identifies that
environment. Generate plans or manifests first and show the review/rollback
path. Never infer production approval from a request to edit configuration.

## Bundled resources

The references cover CI/CD, IaC, and deployment strategies. The scripts can
generate files and the Terraform helper invokes local Terraform commands; run
them only for an authorized target, prefer dry-run/plan behavior, and inspect
every generated diff before accepting it.
