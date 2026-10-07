import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect


def test_initial_migration_roundtrip(tmp_path: Path) -> None:
    database = tmp_path / "migration.db"
    env = dict(os.environ, DATABASE_URL=f"sqlite+aiosqlite:///{database.as_posix()}")
    root = Path(__file__).resolve().parents[2]
    for target in ["head", "base", "head"]:
        command = "downgrade" if target == "base" else "upgrade"
        result = subprocess.run(
            [sys.executable, "-m", "alembic", command, target],
            env=env,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        engine = create_engine(f"sqlite:///{database.as_posix()}")
        try:
            tables = set(inspect(engine).get_table_names())
            expected = {"alembic_version"}
            if target == "head":
                expected |= {
                    "users",
                    "tasks",
                    "task_steps",
                    "agent_runs",
                    "artifacts",
                    "knowledge_sources",
                    "knowledge_chunks",
                    "approvals",
                    "payment_drafts",
                    "audit_events",
                    "accounting_sync_runs",
                    "result_reviews",
                    "consultant_plus_search_events",
                    "execution_checkpoints",
                    "provider_calls",
                    "dead_letter_entries",
                    "companies",
                    "company_memberships",
                    "process_runtime",
                    "capability_grants",
                    "process_schedules",
                    "refresh_tokens",
                    "invitations",
                    "legal_change_radar_runs",
                    "legal_change_radar_reviews",
                }
            assert tables == expected
        finally:
            engine.dispose()
