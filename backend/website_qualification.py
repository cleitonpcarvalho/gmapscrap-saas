"""Authenticated API integrated with saved lead identities and filters."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.auth import get_current_username
from backend.database import get_db
from backend.models import Lead, LeadWebsiteQualification as Result, WebsiteQualificationJob as Job, WebsiteQualificationItem as Item
from backend.services import website_qualification_jobs as jobs

router = APIRouter(prefix="/api/website-qualification", tags=["Website qualification"], dependencies=[Depends(get_current_username)])


class AnalyzeRequest(BaseModel):
    lead_ids: list[int] = Field(min_length=1, max_length=500)
    revalidate: bool = True


@router.post("/jobs", status_code=202)
def analyze(payload: AnalyzeRequest, db: Session = Depends(get_db)):
    result = jobs.enqueue(db, payload.lead_ids, revalidate=payload.revalidate)
    jobs.submit()
    return result


@router.post("/leads/{lead_id}/analyze", status_code=202)
def analyze_lead(lead_id: int, db: Session = Depends(get_db)):
    result = jobs.enqueue(db, [lead_id])
    jobs.submit()
    return result


@router.get("/jobs/{job_id}")
def progress(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None: raise HTTPException(404, "Job not found")
    remaining = db.scalar(select(func.count()).select_from(Item).where(Item.job_id == job_id, Item.active_lead_id.is_not(None))) or 0
    present = db.scalar(select(func.count()).select_from(Item).where(Item.job_id == job_id)) or 0
    processed = job.total - remaining
    failed = (db.scalar(select(func.count()).select_from(Item).where(Item.job_id == job_id, Item.status == "failed")) or 0) + job.total - present
    return {"job_id": job.id, "status": job.status, "total": job.total, "processed": processed, "failed": failed,
            "created_at": job.created_at, "finished_at": job.finished_at}


@router.get("/leads/{lead_id}")
def details(lead_id: int, db: Session = Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if lead is None: raise HTTPException(404, "Lead not found")
    row = db.get(Result, lead_id)
    active = db.scalar(select(Item).where(Item.active_lead_id == lead_id))
    data = jobs.result_data(row)
    # Old observations stay visible but are explicitly marked stale after edits.
    if data:
        import hashlib
        data["stale"] = hashlib.sha256((lead.website or "").encode()).hexdigest() != row.website_sha256
    return {"lead_id": lead_id, "result": data, "job_id": active.job_id if active else None, "status": active.status if active else "idle"}


@router.get("/results")
def results(cms: str | None = None, blog: str | None = None, priority: str | None = None,
            inactive_days: int | None = Query(None, ge=0, le=36500), limit: int = Query(50, ge=1, le=500),
            offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    query = jobs.filter_query(select(Lead.id), cms=cms, blog=blog, priority=priority, inactive_days=inactive_days)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    ids = list(db.scalars(query.order_by(Lead.id).offset(offset).limit(limit)))
    rows = {r.lead_id: jobs.result_data(r) for r in db.scalars(select(Result).where(Result.lead_id.in_(ids)))}
    return {"items": [{"lead_id": lead_id, "result": rows.get(lead_id)} for lead_id in ids], "total": total, "limit": limit, "offset": offset}
