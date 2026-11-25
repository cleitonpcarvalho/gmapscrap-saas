"""Durable qualification queue using existing SQLAlchemy sessions/workers.

Only derived tables are written. A unique active lead claim prevents duplicate
checks across requests/processes. A PostgreSQL session advisory lock elects one
drainer across replicas; at most three sites execute at once. Restart resumes
unfinished read-only HTTP checks, never scraper searches or CRM work.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock
import threading
import hashlib
import uuid

from sqlalchemy import func, select, text

from backend.database import SessionLocal
from backend.models import Lead, LeadWebsiteQualification as Result, WebsiteQualificationJob as Job, WebsiteQualificationItem as Item
from backend.services.website_qualification import analyze_website

executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="website-qualification")
_drain_lock = Lock()
_enqueue_lock = Lock()
_submit_lock = Lock()
_submitted = False
MAX_PENDING = 1000
LOCK_ID = 714271125
_worker_started = False


def result_data(row):
    if row is None:
        return None
    data = {column.name: getattr(row, column.name) for column in Result.__table__.columns}
    if row.last_published_at is not None:
        date = row.last_published_at
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        data["days_since_publication"] = max(0, (datetime.now(timezone.utc).date() - date.date()).days)
        # Priority is refreshed on read so a previously fresh blog can age.
        from backend.services.website_qualification import priority_for
        data["priority"] = priority_for(available=row.site_availability, wordpress=row.wordpress_status,
            blog=row.blog_status, days=data["days_since_publication"], total=row.total_posts)
    if "external_blog_reference_not_crawled" in row.errors and (data["days_since_publication"] is None or data["days_since_publication"] > 30):
        data["priority"] = "INCONCLUSIVE"
    return data


def filter_query(query, *, cms=None, blog=None, priority=None, inactive_days=None):
    from fastapi import HTTPException
    from datetime import timedelta
    choices = {"cms": (cms, {"WordPress", "other", "unknown"}),
               "blog_status": (blog, {"detected", "missing_verified", "inconclusive"}),
               "priority": (priority, {"HIGH", "MEDIUM", "LOW", "INCONCLUSIVE"})}
    if not any([cms, blog, priority, inactive_days is not None]):
        return query
    match = select(Result.lead_id)
    for field, (value, allowed) in choices.items():
        if value:
            if value not in allowed:
                raise HTTPException(422, f"Invalid qualification {field}")
            if field != "priority": match = match.where(getattr(Result, field) == value)
    if inactive_days is not None:
        if not 0 <= inactive_days <= 36500: raise HTTPException(422, "Invalid inactivity")
        match = match.where(Result.last_published_at < datetime.now(timezone.utc) - timedelta(days=inactive_days))
    if priority:
        # Date boundaries match result_data, including aging since last check.
        from sqlalchemy import case, and_
        today = datetime.now(timezone.utc).date()
        recent = datetime.combine(today - timedelta(days=30), datetime.min.time(), tzinfo=timezone.utc)
        medium = datetime.combine(today - timedelta(days=90), datetime.min.time(), tzinfo=timezone.utc)
        effective = case((Result.site_availability != "accessible", "INCONCLUSIVE"),
            (Result.last_published_at >= recent, "LOW"), (Result.last_published_at >= medium, "MEDIUM"),
            (and_(Result.last_published_at.is_not(None), Result.wordpress_status == "confirmed"), "HIGH"),
            (Result.last_published_at.is_not(None), "MEDIUM"),
            (and_((Result.total_posts == 0) | (Result.blog_status == "missing_verified"), Result.wordpress_status == "confirmed"), "HIGH"),
            ((Result.total_posts == 0) | (Result.blog_status == "missing_verified"), "MEDIUM"), else_="INCONCLUSIVE")
        # Keep analyzer-level ambiguity authoritative until a real recent date
        # proves activity. This also works across PostgreSQL and SQLite JSON.
        effective = case((and_(Result.priority == "INCONCLUSIVE", Result.last_published_at.is_(None)), "INCONCLUSIVE"),
                         (and_(Result.priority == "INCONCLUSIVE", Result.last_published_at < recent), "INCONCLUSIVE"), else_=effective)
        match = match.where(effective == priority)
    return query.where(Lead.id.in_(match))


def enqueue(db, lead_ids, *, revalidate=True):
    ids = list(dict.fromkeys(lead_ids))
    with _enqueue_lock:
        if db.bind.dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK_ID + 1})
        pending = db.scalar(select(func.count()).select_from(Item).where(Item.active_lead_id.is_not(None))) or 0
        leads = list(db.scalars(select(Lead).where(Lead.id.in_(ids)).order_by(Lead.id)))
        if len(leads) != len(ids):
            from fastapi import HTTPException
            raise HTTPException(404, "Lead not found")
        active = set(db.scalars(select(Item.active_lead_id).where(Item.active_lead_id.in_(ids))))
        previous = set(db.scalars(select(Result.lead_id).where(Result.lead_id.in_(ids)))) if not revalidate else set()
        targets = [lead for lead in leads if lead.id not in active | previous]
        if pending + len(targets) > MAX_PENDING:
            from fastapi import HTTPException
            raise HTTPException(429, "Qualification queue is full; retry after current jobs complete")
        job = Job(id=str(uuid.uuid4()), total=len(targets), processed=0, failed=0,
                  status="queued" if targets else "completed", finished_at=None if targets else datetime.now(timezone.utc))
        db.add(job)
        db.flush()
        for lead in targets:
            db.add(Item(job_id=job.id, lead_id=lead.id, active_lead_id=lead.id, source_website=lead.website, status="queued"))
        db.commit()
        return {"job_id": job.id, "status": job.status, "total": job.total, "processed": 0,
                "failed": 0, "skipped": len(leads) - len(targets)}


def _run_item(key):
    job_id, lead_id = key
    with SessionLocal() as db:
        item = db.get(Item, key)
        if item is None or item.active_lead_id is None: return
        website = item.source_website
        item.status = "running"
        db.commit()
    try:
        values = analyze_website(website)
        values["website_sha256"] = hashlib.sha256((website or "").encode()).hexdigest()
        with SessionLocal() as db:
            item, lead = db.get(Item, key), db.get(Lead, lead_id)
            if item is None: return
            if lead is None or lead.website != website:
                item.status, item.error = "failed", "website_changed_revalidate"
            else:
                result = db.get(Result, lead_id)
                if result is None:
                    result = Result(lead_id=lead_id, **values)
                    db.add(result)
                else:
                    for field, value in values.items(): setattr(result, field, value)
                item.status = "completed"
            item.active_lead_id = None
            db.commit()
    except Exception:
        # Never persist exception text, requested URLs, response bodies or secrets.
        with SessionLocal() as db:
            item = db.get(Item, key)
            if item:
                item.status, item.error, item.active_lead_id = "failed", "analysis_failed", None
                db.commit()


def drain():
    if not _drain_lock.acquire(blocking=False): return
    connection = None
    try:
        with SessionLocal() as db:
            engine = db.get_bind()
        if engine.dialect.name == "postgresql":
            connection = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
            if not connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_ID}): return
        while True:
            with SessionLocal() as db:
                job = db.scalar(select(Job).where(Job.status.in_(["queued", "running"])).order_by(Job.created_at, Job.id).limit(1))
                if job is None: return
                job.status = "running"
                keys = [(row.job_id, row.lead_id) for row in db.scalars(select(Item).where(Item.job_id == job.id, Item.active_lead_id.is_not(None))).all()]
                job_id = job.id
                db.commit()
            with ThreadPoolExecutor(max_workers=3, thread_name_prefix="website-site") as pool:
                list(pool.map(_run_item, keys))
            with SessionLocal() as db:
                job = db.get(Job, job_id)
                remaining = db.scalar(select(func.count()).select_from(Item).where(Item.job_id == job_id, Item.active_lead_id.is_not(None))) or 0
                present = db.scalar(select(func.count()).select_from(Item).where(Item.job_id == job_id)) or 0
                job.processed = job.total - remaining
                job.failed = (db.scalar(select(func.count()).select_from(Item).where(Item.job_id == job_id, Item.status == "failed")) or 0) + job.total - present
                job.status, job.finished_at = "completed", datetime.now(timezone.utc)
                db.commit()
    finally:
        if connection is not None:
            try: connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_ID})
            finally: connection.close()
        _drain_lock.release()


def submit():
    global _submitted
    with _submit_lock:
        if _submitted: return None
        _submitted = True
    def run():
        global _submitted
        try: drain()
        finally:
            with _submit_lock: _submitted = False
    return executor.submit(run)


def start_worker():
    """Recover persisted checks after restart and cover enqueue/drainer races."""
    global _worker_started
    with _enqueue_lock:
        if _worker_started: return
        _worker_started = True
    def poll():
        import time
        while True:
            try: drain()
            except Exception: pass  # durable queue remains retryable; no sensitive logs
            time.sleep(5)
    threading.Thread(target=poll, name="website-qualification-poll", daemon=True).start()
