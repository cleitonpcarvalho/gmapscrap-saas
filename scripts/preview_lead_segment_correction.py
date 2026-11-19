"""Read-only preview only. There is deliberately no apply option or startup migration."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402
from backend.database import engine  # noqa: E402

OLD_NICHE = "São José do Rio Preto"
OLD_LOCATION = "Brindes"


def preview(connection) -> dict:
    rows = connection.execute(
        text(
            "SELECT l.id, l.run_id FROM leads l JOIN search_runs r ON r.id = l.run_id "
            "WHERE r.niche = :niche AND r.location = :location ORDER BY l.id"
        ),
        {"niche": OLD_NICHE, "location": OLD_LOCATION},
    ).all()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "affected_record_count": len(rows),
        "lead_ids": [row.id for row in rows],
        "search_run_ids": sorted({row.run_id for row in rows}),
        "before": {"niche": OLD_NICHE, "location": OLD_LOCATION},
        "after": {"niche": OLD_LOCATION, "location": OLD_NICHE},
        "storage_note": "Lead niche/locality are inherited from search_runs.niche/location; no lead fields need changing.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if engine.dialect.name != "postgresql":
        parser.error("This production preview requires PostgreSQL read-only transaction enforcement.")
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout = '30s'"))
            columns = connection.execute(text(
                "SELECT table_name, column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name IN ('leads', 'search_runs', 'niches') "
                "ORDER BY table_name, ordinal_position"
            )).mappings().all()
            result = preview(connection)
            result["schema"] = [dict(column) for column in columns]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "schema"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
