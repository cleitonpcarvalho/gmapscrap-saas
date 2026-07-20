#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.database import SessionLocal, init_db  # noqa: E402
from backend.models import Lead, LeadEmailPreference  # noqa: E402
from backend.services.email_validation import validate_email_address  # noqa: E402


@dataclass(frozen=True, slots=True)
class LeadEmailRow:
    lead_id: int
    name: str
    website: str
    email: str


@dataclass(frozen=True, slots=True)
class ValidationRow:
    lead: LeadEmailRow
    normalized_email: str
    status: str
    reasons: tuple[str, ...]
    domain_matches_website: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Valida e-mails existentes da tabela leads.")
    parser.add_argument("--apply", action="store_true", help="Marca e-mails inválidos como do_not_contact.")
    parser.add_argument("--limit", type=int, default=0, help="Limita a quantidade de leads avaliados.")
    parser.add_argument(
        "--mark-unknown",
        action="store_true",
        help="Também marca resultados DNS desconhecidos como do_not_contact.",
    )
    parser.add_argument("--workers", type=int, default=12, help="Quantidade de validações DNS em paralelo.")
    parser.add_argument("--init-db", action="store_true", help="Executa init_db antes da validação.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.init_db:
        init_db()

    output_dir = ROOT_DIR / "tmp"
    output_dir.mkdir(exist_ok=True)
    report_path = output_dir / f"email-validation-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"

    db = SessionLocal()
    counters: Counter[str] = Counter()
    marked = 0

    try:
        stmt = select(Lead.id, Lead.name, Lead.website, Lead.email).where(Lead.email != "").order_by(Lead.id)
        if args.limit:
            stmt = stmt.limit(args.limit)

        leads = [
            LeadEmailRow(
                lead_id=lead_id,
                name=name,
                website=website or "",
                email=email,
            )
            for lead_id, name, website, email in db.execute(stmt).all()
        ]
        validation_rows = _validate_rows(leads, max(1, args.workers))

        with report_path.open("w", newline="", encoding="utf-8") as report_file:
            writer = csv.DictWriter(
                report_file,
                fieldnames=[
                    "lead_id",
                    "name",
                    "website",
                    "email",
                    "normalized_email",
                    "status",
                    "reasons",
                    "domain_matches_website",
                    "action",
                ],
            )
            writer.writeheader()

            for row in validation_rows:
                counters[row.status] += 1
                reasons = ",".join(row.reasons)
                should_mark = row.status == "invalid" or (args.mark_unknown and row.status == "unknown")
                action = "none"

                if should_mark:
                    action = "would_mark"
                    if args.apply:
                        preference = db.get(LeadEmailPreference, row.lead.lead_id)
                        if not preference:
                            preference = LeadEmailPreference(lead_id=row.lead.lead_id)
                            db.add(preference)

                        preference.do_not_contact = True
                        preference.reason = f"invalid_email: {reasons or row.status}"
                        action = "marked"
                        marked += 1

                writer.writerow(
                    {
                        "lead_id": row.lead.lead_id,
                        "name": row.lead.name,
                        "website": row.lead.website,
                        "email": row.lead.email,
                        "normalized_email": row.normalized_email,
                        "status": row.status,
                        "reasons": reasons,
                        "domain_matches_website": str(row.domain_matches_website).lower(),
                        "action": action,
                    }
                )

        if args.apply:
            db.commit()

    finally:
        db.close()

    total = sum(counters.values())
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"Modo: {mode}")
    print(f"Relatorio: {report_path}")
    print(f"Avaliados: {total}")
    print(f"Validos: {counters['valid']}")
    print(f"Invalidos: {counters['invalid']}")
    print(f"Desconhecidos: {counters['unknown']}")
    print(f"Marcados: {marked}")
    return 0


def _validate_rows(leads: list[LeadEmailRow], workers: int) -> list[ValidationRow]:
    if not leads:
        return []

    results: list[ValidationRow] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_validate_row, lead): lead for lead in leads}
        for index, future in enumerate(as_completed(futures), start=1):
            results.append(future.result())
            if index % 50 == 0:
                print(f"Validados: {index}/{len(leads)}")

    return sorted(results, key=lambda row: row.lead.lead_id)


def _validate_row(lead: LeadEmailRow) -> ValidationRow:
    result = validate_email_address(lead.email, lead.website)
    return ValidationRow(
        lead=lead,
        normalized_email=result.normalized_email,
        status=result.status,
        reasons=result.reasons,
        domain_matches_website=result.domain_matches_website,
    )


if __name__ == "__main__":
    raise SystemExit(main())
