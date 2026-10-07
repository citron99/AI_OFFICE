import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("top_k,exit_code", [(3, 0), (1, 1)])
def test_offline_evaluation_gate(top_k: int, exit_code: int) -> None:
    root = Path(__file__).resolve().parents[2]
    run = subprocess.run(
        [sys.executable, "scripts/eval_retrieval.py", "--check", "--top-k", str(top_k)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert run.returncode == exit_code, run.stderr
    report = json.loads(run.stdout)
    assert report["documents"] == 12
    assert report["positive_cases"] == 13
    assert report["negative_cases"] == 6
    assert report["retrieval_version"] == "mock-hash-lexical-v2"
    assert report["passed"] == (exit_code == 0)
    if top_k == 3:
        assert all(value == 1.0 for value in report["metrics"].values())
    else:
        # One query needs two documents: the gate must fail when k=1 hides one.
        assert report["metrics"]["recall_at_k"] < 0.99
