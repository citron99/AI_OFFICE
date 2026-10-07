"""Offline retrieval regression on isolated SQLite. Never uses live data or LLMs.

Run: uv run python scripts/eval_retrieval.py --check
Outputs JSON to stdout and optionally a new --output file; never alters application databases.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.knowledge.embeddings import EmbeddingProvider

# Keep direct execution (`python scripts/eval_retrieval.py`) independent of an
# editable-package install, as used in CI and incident-response environments.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def load_suite(suite_path: Path | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    fixtures = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
    if suite_path is not None:
        suite = json.loads(suite_path.read_text(encoding="utf-8"))
        return suite["documents"], suite
    corpus = json.loads((fixtures / "legal_corpus.json").read_text(encoding="utf-8"))
    suite = json.loads((fixtures / "retrieval_eval.json").read_text(encoding="utf-8"))
    corpus.extend(suite["extra_documents"])
    return corpus, suite


async def evaluate(
    top_k: int = 3,
    *,
    provider: EmbeddingProvider | None = None,
    suite_path: Path | None = None,
    min_score: float = 0.3,
) -> dict[str, Any]:
    # Keep CLI validation cheap: importing the application stack is deferred
    # until an evaluation will actually run.
    import httpx

    from app.config import Settings
    from app.db.base import Base
    from app.db.session import create_engine, create_session_factory
    from app.knowledge.embeddings import HashEmbeddingProvider
    from app.knowledge.evaluation import score_case
    from app.knowledge.local_embeddings import LocalSentenceTransformer
    from app.main import create_app
    from app.models.knowledge import SearchRequest
    from app.services.knowledge import KnowledgeService

    started = time.perf_counter()
    provider = provider or HashEmbeddingProvider()
    corpus, suite = await asyncio.to_thread(load_suite, suite_path)
    titles = {doc["title"] for doc in corpus}
    if len(titles) != len(corpus):
        raise ValueError("Evaluation corpus titles must be unique")
    case_ids: set[str] = set()
    for case in suite["cases"]:
        if case["id"] in case_ids or not set(case["expected"]).issubset(titles):
            raise ValueError("Invalid evaluation case ID or expected source")
        case_ids.add(case["id"])
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    records = []
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        with tempfile.TemporaryDirectory(prefix="ai-office-eval-") as temporary:
            settings = Settings(
                app_env="test",
                database_url="sqlite+aiosqlite:///:memory:",
                llm_provider="mock",
                embedding_provider="mock",
                semantic_min_score=min_score,
                legal_analysis_enabled=False,
                auto_create_schema=False,
                max_upload_bytes=10 * 1024 * 1024,
                upload_dir=Path(temporary),
            )
            factory = create_session_factory(engine)
            app = create_app(
                settings=settings,
                engine=engine,
                session_factory=factory,
                embedding_provider=provider,
            )
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url="http://test"
                ) as client:
                    for document in corpus:
                        response = await client.post(
                            "/api/v1/files",
                            files={
                                "file": ("fixture.txt", document["text"].encode(), "text/plain"),
                            },
                        )
                        response.raise_for_status()
                        source = await client.post(
                            "/api/v1/knowledge/sources",
                            json={
                                "artifact_id": response.json()["id"],
                                "title": document["title"],
                                "document_type": document["document_type"],
                                "jurisdiction": "LV",
                                "authority": "SYNTHETIC TEST, NOT LAW",
                                "version": "test-v1",
                                "status": "ACTIVE",
                                "effective_from": "2026-01-01",
                            },
                        )
                        source.raise_for_status()
                async with factory() as session:
                    service = KnowledgeService(session, settings, provider)
                    for case in suite["cases"]:
                        query = SearchRequest(
                            query=case["query"],
                            jurisdiction=case.get("jurisdiction", "LV"),
                            effective_on=case.get("effective_on", "2026-08-27"),
                            document_types=case.get("document_types", []),
                            top_k=top_k,
                        )
                        result = await service.search(
                            query,
                            owner_id=case.get("owner_id", "usr_demo_owner"),
                            company_id=case.get("company_id", "comp_demo"),
                        )
                        returned = list(dict.fromkeys(hit.title for hit in result.hits))
                        records.append(
                            {
                                "id": case["id"],
                                "category": case.get("category", "legacy"),
                                "expected": case["expected"],
                                "returned": returned,
                                "scores": [hit.score for hit in result.hits],
                                **score_case(case["expected"], returned),
                            }
                        )
    finally:
        await engine.dispose()
    positive = [row for row in records if row["expected"]]
    negative = [row for row in records if not row["expected"]]
    if not positive or not negative:
        raise ValueError("Evaluation must contain both positive and negative cases")
    metrics = {
        "recall_at_k": sum(row["recall_at_k"] for row in positive) / len(positive),
        "precision_returned": sum(row["precision_returned"] for row in positive) / len(positive),
        "mrr_at_k": sum(row["reciprocal_rank"] for row in positive) / len(positive),
        "negative_empty_rate": sum(not row["returned"] for row in negative) / len(negative),
    }
    return {
        "suite": suite["version"],
        "suite_sha256": hashlib.sha256(
            json.dumps({"documents": corpus, "suite": suite}, sort_keys=True).encode()
        ).hexdigest(),
        "backend": "sqlite",
        "embedding_model": provider.model_id,
        "embedding_dimensions": provider.dimensions,
        "retrieval_version": service.retrieval_version,
        "semantic_min_score": min_score if provider.semantic else None,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "top_k": top_k,
        "documents": len(corpus),
        "positive_cases": len(positive),
        "negative_cases": len(negative),
        "metrics": metrics,
        "categories": {
            category: {
                "cases": len(group),
                "exact_set_rate": sum(set(row["returned"]) == set(row["expected"]) for row in group)
                / len(group),
            }
            for category in sorted({row["category"] for row in records})
            if (group := [row for row in records if row["category"] == category])
        },
        "runtime_versions": {
            name: importlib.metadata.version(name)
            for name in (
                ["sentence-transformers", "torch", "transformers"]
                if isinstance(provider, LocalSentenceTransformer)
                else []
            )
        },
        "passed": all(value >= 0.99 for value in metrics.values()),
        "cases": records,
        "limitations": [
            "Synthetic developer-authored suite, not independent legal-quality validation.",
            "SQLite evaluation; no live LLM. Do not tune and claim holdout results on this suite.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if any metric is below 0.99")
    parser.add_argument("--top-k", type=int, default=3, choices=range(1, 51))
    parser.add_argument("--suite", type=Path, help="Standalone JSON suite with documents and cases")
    parser.add_argument("--model-path", type=Path, help="Trusted local snapshot; never downloaded")
    parser.add_argument("--dimensions", type=int, default=384)
    parser.add_argument("--min-score", type=float, default=0.3)
    parser.add_argument("--output", type=Path, help="Also save the JSON report to a new file")
    args = parser.parse_args()
    if not 0 <= args.min_score <= 1:
        parser.error("--min-score must be between 0 and 1")
    if args.output is not None and args.output.exists():
        parser.error("--output already exists; choose a new report path")
    from app.knowledge.embeddings import HashEmbeddingProvider
    from app.knowledge.local_embeddings import LocalSentenceTransformer

    provider = (
        LocalSentenceTransformer(args.model_path, args.dimensions)
        if args.model_path is not None
        else HashEmbeddingProvider()
    )
    report = asyncio.run(
        evaluate(
            top_k=args.top_k,
            provider=provider,
            suite_path=args.suite,
            min_score=args.min_score,
        )
    )
    rendered = json.dumps(report, ensure_ascii=True, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(rendered + "\n")
    print(rendered)
    exit_code = 1 if args.check and not report["passed"] else 0
    # A pooled SQLite connection keeps the aiosqlite worker alive, which makes
    # interpreter shutdown join forever on an idle queue. The report is fully
    # written and flushed above, so exit the process explicitly.
    sys.stdout.flush()
    import os

    os._exit(exit_code)


if __name__ == "__main__":
    main()
