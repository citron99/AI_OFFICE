"""Real HTTP smoke on a temporary migrated SQLite database; no API keys required."""

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="ai-office-smoke-") as directory:
        temporary = Path(directory)
        env = dict(
            os.environ,
            DATABASE_URL=f"sqlite+aiosqlite:///{(temporary / 'smoke.db').as_posix()}",
            UPLOAD_DIR=str(temporary / "uploads"),
            APP_ENV="test",
            LLM_PROVIDER="mock",
            EMBEDDING_PROVIDER="mock",
            LEGAL_ANALYSIS_ENABLED="false",
            AUTO_CREATE_SCHEMA="false",
        )
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=root,
            env=env,
            check=True,
            timeout=30,
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=root,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as client:
                deadline = time.monotonic() + 10
                while True:
                    try:
                        client.get("/health").raise_for_status()
                        break
                    except httpx.TransportError:
                        if server.poll() is not None or time.monotonic() >= deadline:
                            raise RuntimeError("Smoke server did not start") from None
                        time.sleep(0.1)
                client.get("/ready").raise_for_status()
                uploaded = client.post(
                    "/api/v1/files",
                    files={"file": ("demo.txt", b"synthetic contract", "text/plain")},
                )
                uploaded.raise_for_status()
                created = client.post(
                    "/api/v1/tasks",
                    json={
                        "message": "Review contract",
                        "attachment_ids": [uploaded.json()["id"]],
                        "jurisdiction": "LV",
                        "effective_on": "2026-08-27",
                    },
                )
                created.raise_for_status()
                result = created.json()
                assert result["state"] == "completed"
                # Consultant+ now serves the licensed LV corpus: the route retrieves.
                legal = result["result"]
                assert legal["status"] in {"retrieval_only", "legal_source_not_found"}, legal
                assert legal["consultant_plus"]["searched"] is True
                fetched = client.get(f"/api/v1/tasks/{result['task_id']}")
                fetched.raise_for_status()
                assert fetched.json() == result
                source = client.post(
                    "/api/v1/knowledge/sources",
                    json={
                        "artifact_id": uploaded.json()["id"],
                        "title": "SYNTHETIC smoke contract",
                        "jurisdiction": "LV",
                        "document_type": "contract",
                        "authority": "Synthetic smoke test, not law",
                        "version": "test-v1",
                        "effective_from": "2026-01-01",
                        "status": "ACTIVE",
                    },
                )
                source.raise_for_status()
                waiting = client.post("/api/v1/tasks", json={"message": "Review contract"})
                waiting.raise_for_status()
                assert waiting.json()["state"] == "waiting_input"
                task_id = waiting.json()["task_id"]
                clarified = client.post(
                    f"/api/v1/tasks/{task_id}/clarify",
                    json={
                        "jurisdiction": "LV",
                        "effective_on": "2026-08-27",
                    },
                )
                clarified.raise_for_status()
                legal_result = clarified.json()
                assert legal_result["result"]["status"] == "retrieval_only"
                assert legal_result["result"]["citations"][0]["source_id"] == source.json()["id"]
                assert client.get(f"/api/v1/tasks/{task_id}").json() == legal_result
                print("PASS: DB -> upload -> KB -> clarification -> persisted legal citations")
        finally:
            if os.name == "nt" and server.poll() is None:
                # Windows venv launchers may own a separate Python child. Stop only
                # this smoke server's process tree before TemporaryDirectory cleanup.
                subprocess.run(
                    ["taskkill", "/PID", str(server.pid), "/T", "/F"],
                    check=True,
                    capture_output=True,
                    timeout=10,
                )
            elif server.poll() is None:
                server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


if __name__ == "__main__":
    main()
