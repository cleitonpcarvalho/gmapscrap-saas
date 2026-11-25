import csv
from datetime import datetime, timezone, timedelta
from io import BytesIO, StringIO
import json
import threading
import time
from types import SimpleNamespace
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend import auth, main
from backend.database import Base, get_db
from backend.models import Lead, SearchRun, LeadWebsiteQualification as Result, WebsiteQualificationJob as Job, WebsiteQualificationItem as Item
from backend.services import website_qualification_jobs as jobs
from backend.services.qualification_exports import FIELDS


@pytest.fixture()
def api(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "qualification.db"), connect_args={"check_same_thread":False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(jobs, "SessionLocal", factory)
    monkeypatch.setattr(jobs, "submit", lambda: None)
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(app_username="test-user",session_secret="test-only",session_cookie_secure=False))
    def database():
        with factory() as session: yield session
    main.app.dependency_overrides[get_db] = database
    with factory() as db:
        run = SearchRun(id=29,niche="Services",location="Recife",status="paused")
        db.add(run)
        db.add_all(Lead(id=i,search_run=run,name="=FORMULA()" if i == 1 else f"Company {i}",address="Address",website=f"https://company{i}.example/") for i in range(1,8))
        db.commit()
    client = TestClient(main.app)
    client.cookies.set(auth.COOKIE_NAME,auth.create_session_token("test-user"))
    yield client, factory
    main.app.dependency_overrides.clear()
    client.close(); engine.dispose()


def outcome(**updates):
    return dict(normalized_website="https://company.example/",website_sha256="a"*64,site_availability="accessible",cms="WordPress",cms_name="WordPress",
                wordpress_status="confirmed",blog_status="detected",blog_url="https://company.example/blog",total_posts=0,
                last_published_at=None,last_post_title=None,last_post_url=None,days_since_publication=None,priority="HIGH",
                validation_status="validated",checked_at=datetime.now(timezone.utc),evidence=[{"source":"wp_posts_api","reason":"no_posts_exposed"}],errors=[],**updates)


def observation(**updates):
    values = outcome(); values.update(updates); return values


def test_auth_required_for_read_single_bulk_progress_and_exports(api):
    client,_=api; client.cookies.clear()
    for method,path,data in [("GET","/api/website-qualification/results",None),("GET","/api/website-qualification/leads/1",None),
                            ("POST","/api/website-qualification/leads/1/analyze",None),("POST","/api/website-qualification/jobs",{"lead_ids":[1]}),
                            ("GET","/api/website-qualification/jobs/missing",None),("GET","/api/leads/export.xlsx",None)]:
        assert client.request(method,path,json=data).status_code == 401


def test_duplicate_claims_queue_cap_and_revalidation_preserves_old_result(api, monkeypatch):
    client,factory=api
    with factory() as db: db.add(Result(lead_id=1,**outcome())); db.commit()
    first=client.post("/api/website-qualification/jobs",json={"lead_ids":[1,1,2]}).json()
    assert first["total"] == 2
    second=client.post("/api/website-qualification/jobs",json={"lead_ids":[1]}).json()
    assert second["total"] == 0 and second["skipped"] == 1
    details=client.get("/api/website-qualification/leads/1").json()
    assert details["result"]["total_posts"] == 0 and details["job_id"] == first["job_id"]
    monkeypatch.setattr(jobs,"MAX_PENDING",2)
    assert client.post("/api/website-qualification/jobs",json={"lead_ids":[3]}).status_code == 429
    assert client.post("/api/website-qualification/jobs",json={"lead_ids":[999]}).status_code == 404
    assert client.post("/api/website-qualification/jobs",json={"lead_ids":[]}).status_code == 422


def test_bounded_bulk_workers_restart_progress_and_original_records_unchanged(api, monkeypatch):
    client,factory=api
    with factory() as db:
        original = [(r.id,r.name,r.website,r.email,r.address,r.phone) for r in db.scalars(select(Lead).order_by(Lead.id))]
    active,maximum=0,0
    lock=threading.Lock()
    def analyze(url):
        nonlocal active,maximum
        with lock: active+=1; maximum=max(maximum,active)
        time.sleep(.025)
        with lock: active-=1
        values=outcome(); values.pop("website_sha256"); values["normalized_website"]=url
        return values
    monkeypatch.setattr(jobs,"analyze_website",analyze)
    started=client.post("/api/website-qualification/jobs",json={"lead_ids":list(range(1,8))}).json()
    with factory() as db:
        # Simulate restart after an interrupted attempt. Read-only HTTP can retry.
        db.get(Item,(started["job_id"],1)).status="running"; db.get(Job,started["job_id"]).status="running"; db.commit()
    jobs.drain()
    progress=client.get("/api/website-qualification/jobs/"+started["job_id"]).json()
    assert progress["status"] == "completed" and progress["processed"] == 7 and progress["failed"] == 0
    assert 1 < maximum <= 3
    with factory() as db:
        assert [(r.id,r.name,r.website,r.email,r.address,r.phone) for r in db.scalars(select(Lead).order_by(Lead.id))] == original
        assert db.get(SearchRun,29).status == "paused"
        assert len(list(db.scalars(select(Result)))) == 7
        assert not list(db.scalars(select(Item).where(Item.active_lead_id.is_not(None))))
    assert client.get("/api/website-qualification/leads/1").json()["result"]["stale"] is False


def test_edited_website_and_failure_do_not_overwrite_previous_result(api, monkeypatch):
    client,factory=api
    with factory() as db: db.add(Result(lead_id=1,**outcome())); db.commit()
    def analyze(_):
        with factory() as db:
            db.get(Lead,1).website="https://changed.example/"; db.commit()
        return {k:v for k,v in outcome().items() if k!="website_sha256"}
    monkeypatch.setattr(jobs,"analyze_website",analyze)
    job=client.post("/api/website-qualification/leads/1/analyze").json()
    jobs.drain()
    assert client.get("/api/website-qualification/jobs/"+job["job_id"]).json()["failed"] == 1
    with factory() as db:
        assert db.get(Result,1).normalized_website == "https://company.example/"
        assert db.get(Item,(job["job_id"],1)).error == "website_changed_revalidate"
    assert client.get("/api/website-qualification/leads/1").json()["result"]["stale"] is True


def test_filters_server_pagination_and_live_recency_priority(api):
    client,factory=api
    now=datetime.now(timezone.utc)
    with factory() as db:
        db.add(Result(lead_id=1,**outcome()))
        db.add(Result(lead_id=2,**observation(cms="other",cms_name="Ghost",wordpress_status="not_detected",total_posts=None,last_published_at=now-timedelta(days=100),days_since_publication=1,priority="LOW")))
        db.add(Result(lead_id=3,**observation(last_published_at=now-timedelta(days=5),total_posts=10,days_since_publication=5,priority="LOW")))
        db.commit()
    response=client.get("/api/leads?cms=WordPress&priority=HIGH")
    assert [r["id"] for r in response.json()] == [1]
    result=client.get("/api/website-qualification/results?cms=other&priority=MEDIUM&inactive_days=90").json()
    assert result["total"] == 1 and result["items"][0]["lead_id"] == 2
    assert result["items"][0]["result"]["days_since_publication"] == 100
    result=client.get("/api/website-qualification/results?limit=1&offset=1").json()
    assert result["total"] == 7 and result["items"][0]["lead_id"] == 2
    assert client.get("/api/leads?limit=2&offset=2").headers["x-total-count"] == "7"
    assert len(client.get("/api/leads?limit=2&offset=2").json()) == 2
    for query in ("cms=invalid","priority=invalid","blog=missing","inactive_days=-1","limit=501"):
        assert client.get("/api/website-qualification/results?"+query).status_code == 422


def test_csv_and_xlsx_all_fields_nulls_and_formula_text_escaping(api):
    client,factory=api
    with factory() as db:
        db.add(Result(lead_id=1,**observation(last_post_title="=HYPERLINK(\"bad\")"))); db.commit()
    response=client.get("/api/leads/export.csv?priority=HIGH")
    assert response.status_code == 200
    rows=list(csv.DictReader(StringIO(response.content.decode("utf-8-sig"))))
    assert len(rows) == 1 and rows[0]["Nome"] == "'=FORMULA()"
    assert rows[0]["last_post_title"].startswith("'=") and rows[0]["last_published_at"] == ""
    assert set(FIELDS).issubset(rows[0]) and rows[0]["total_posts"] == "0"
    response=client.get("/api/leads/export.xlsx?priority=HIGH")
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        xml=ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        assert not any(e.tag.endswith("}f") for e in xml.iter())
        texts=[e.text for e in xml.iter() if e.tag.endswith("}t")]
        assert all(field in texts for field in FIELDS)
        assert "'=FORMULA()" in texts


def test_duplicate_submissions_do_not_grow_an_unbounded_executor_queue(monkeypatch):
    scheduled,drained=[],[]
    monkeypatch.setattr(jobs,"_submitted",False)
    monkeypatch.setattr(jobs,"executor",SimpleNamespace(submit=lambda task:scheduled.append(task)))
    monkeypatch.setattr(jobs,"drain",lambda:drained.append(True))
    for _ in range(100): jobs.submit()
    assert len(scheduled) == 1
    scheduled[0]()
    assert drained == [True]
    jobs.submit()
    assert len(scheduled) == 2
    scheduled[1]()
