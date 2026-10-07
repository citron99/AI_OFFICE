---
name: rag-architect
description: Design, tune, or evaluate AI_OFFICE retrieval, chunking, embeddings, pgvector search, reranking, citation grounding, and legal knowledge ingestion.
license: MIT
metadata:
  upstream_repo: alirezarezvani/claude-skills
  upstream_commit: 19392f7a08264ed00486a251f5b2098321771f94
  adaptation: codex-project
---

# RAG Architect for AI_OFFICE

The project already has a legal RAG pipeline and closed retrieval fixtures. Base
recommendations on the actual corpus, query set, and code rather than generic
vector-database advice.

## Workflow

1. Inspect `docs/LEGAL_RAG.md`, `docs/RETRIEVAL_EVAL.md`,
   `docs/SEMANTIC_SEARCH.md`, the knowledge service, and current evaluation
   fixtures.
2. Establish the failure being optimized: retrieval miss, noisy context,
   citation mismatch, latency, index migration, or tenant isolation.
3. Measure the current baseline with the repository evaluation script.
4. Change one retrieval variable at a time: parsing/chunking, filters,
   embeddings, hybrid retrieval, ranking, or prompt context assembly.
5. Re-run retrieval and legal contract tests; report metric deltas and poor
   examples, not only aggregate scores.

## Hard rules

- Legal analysis still requires the configured ConsultantPlus source gate.
- Uploaded attachments are evidence to analyze, not trusted legal authority.
- Retrieval and indexes remain scoped by company and source provenance.
- A RAG change is incomplete without an evaluation run or a clearly stated
  reason the required corpus/environment was unavailable.
- Model availability, benchmark rankings, and pricing are time-sensitive; verify
  current claims from primary provider documentation when they matter.

The bundled optimizer, designer, and evaluator are optional scratch tools. The
project's own fixtures and `scripts/eval_retrieval.py` take precedence. Read the
references only for the specific chunking, embedding, or metric question at hand.
