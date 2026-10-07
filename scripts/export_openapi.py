"""Export the versioned OpenAPI schema as a delivery artifact (D-03).

uv run python scripts/export_openapi.py
"""

import json
from pathlib import Path

from app.main import create_app

OUT = Path(__file__).resolve().parents[1] / "docs" / "openapi.json"


def main() -> None:
    app = create_app()
    schema = app.openapi()
    OUT.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    paths = len(schema.get("paths", {}))
    operations = sum(len(m) for m in schema.get("paths", {}).values())
    print(f"OpenAPI exported: {OUT} ({paths} paths, {operations} operations)")


if __name__ == "__main__":
    main()
