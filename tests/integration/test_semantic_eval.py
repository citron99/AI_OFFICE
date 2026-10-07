import importlib.util
import json
from pathlib import Path

import pytest


def evaluator():
    path = Path(__file__).resolve().parents[2] / "scripts" / "eval_retrieval.py"
    spec = importlib.util.spec_from_file_location("eval_retrieval_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Vectors:
    model_id = "test-eval-semantic"
    dimensions = 2
    semantic = True

    def embed(self, text: str) -> list[float]:
        return [1.0, 0.0] if text in {"payment", "remuneration"} else [0.0, 1.0]


async def test_evaluation_injects_same_provider_and_reports_actual_identity(tmp_path: Path) -> None:
    suite = tmp_path / "suite.json"
    suite.write_text(
        json.dumps(
            {
                "version": "test-only",
                "documents": [
                    {"title": "SYNTHETIC", "text": "payment", "document_type": "contract"}
                ],
                "cases": [
                    {"id": "paraphrase", "query": "remuneration", "expected": ["SYNTHETIC"]},
                    {"id": "negative", "query": "astronomy", "expected": []},
                ],
            }
        ),
        encoding="utf-8",
    )
    report = await evaluator().evaluate(provider=Vectors(), suite_path=suite)
    assert report["passed"]
    assert report["embedding_model"] == Vectors.model_id
    assert report["embedding_dimensions"] == 2
    assert report["retrieval_version"] == "semantic-cosine-v1"
    assert report["semantic_min_score"] == 0.3
    assert report["cases"][0]["scores"] == [1.0]
    mock = await evaluator().evaluate(suite_path=suite)
    assert not mock["passed"]
    assert mock["cases"][0]["returned"] == []


@pytest.mark.parametrize("score", ["nan", "inf", "-0.1", "1.1"])
def test_cli_rejects_invalid_threshold(score: str) -> None:
    import subprocess
    import sys

    path = Path(__file__).resolve().parents[2] / "scripts" / "eval_retrieval.py"
    run = subprocess.run(
        [sys.executable, str(path), "--min-score", score],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert run.returncode == 2
    assert "--min-score" in run.stderr
