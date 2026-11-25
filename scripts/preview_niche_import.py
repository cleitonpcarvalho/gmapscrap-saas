"""Preview historical niche registration. There is deliberately no apply mode."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from pydantic import ValidationError
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.schemas import NicheWrite  # noqa: E402


def preview(connection) -> dict:
    """Read every search label, including runs with no saved leads, without DML."""
    source = connection.execute(text(
        "SELECT r.niche, COUNT(DISTINCT r.id) AS search_run_count, COUNT(l.id) AS lead_count "
        "FROM search_runs r LEFT JOIN leads l ON l.run_id = r.id "
        "GROUP BY r.niche ORDER BY r.niche"
    )).mappings().all()
    existing = connection.execute(text("SELECT id, name FROM niches ORDER BY id")).mappings().all()
    existing_keys = set()
    invalid_existing = []
    for item in existing:
        try:
            existing_keys.add(NicheWrite(name=item["name"]).name.casefold())
        except ValidationError:
            invalid_existing.append({"id": item["id"], "name": item["name"]})

    grouped = {}
    rejected = []
    for row in source:
        try:
            name = NicheWrite(name=row["niche"]).name
        except ValidationError:
            rejected.append({"raw_name": row["niche"], "search_run_count": row["search_run_count"],
                "lead_count": row["lead_count"], "reason": "Rejected by the existing authenticated niche API validation."})
            continue
        entry = grouped.setdefault(name.casefold(), {"name": name, "source_names": [],
            "search_run_count": 0, "lead_count": 0})
        entry["source_names"].append(row["niche"])
        entry["search_run_count"] += row["search_run_count"]
        entry["lead_count"] += row["lead_count"]

    candidates = sorted(grouped.values(), key=lambda row: row["name"].casefold())
    for item in candidates:
        item["already_registered"] = item["name"].casefold() in existing_keys
    names = [item["name"] for item in candidates if not item["already_registered"]]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "import_executed": False,
        "requires_explicit_approval": True,
        "source_totals": {
            "search_runs": connection.scalar(text("SELECT COUNT(*) FROM search_runs")),
            "leads": connection.scalar(text("SELECT COUNT(*) FROM leads")),
            "registered_niches": len(existing),
            "distinct_raw_labels": len(source),
            "distinct_valid_names": len(candidates),
        },
        "new_record_count": len(names),
        "new_names": names,
        "candidates": candidates,
        "rejected_source_names": rejected,
        "invalid_existing_registry_names": invalid_existing,
        "scope": "Leads inherit niche labels from search_runs. All historical runs, including empty runs, are included.",
        "approved_import_method": "After explicit approval, POST only approved new_names to the existing authenticated /api/niches endpoint; recheck duplicates first. No lead or search updates.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # Importing the engine does not start the app or initialize the schema.
    from backend.database import engine

    if engine.dialect.name != "postgresql":
        parser.error("Production preview requires PostgreSQL read-only transaction enforcement.")
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout = '30s'"))
            connection.execute(text("SET LOCAL search_path = public, pg_catalog"))
            result = preview(connection)
            result["database_read_only"] = connection.scalar(text("SHOW transaction_read_only")) == "on"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"read_only": True, "new_record_count": result["new_record_count"],
        "new_names": result["new_names"], "import_executed": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
