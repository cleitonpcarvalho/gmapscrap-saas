from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend import main
from backend.database import Base
from backend.models import Lead, LeadTag, SearchRun, Tag
from backend.schemas import LeadTagsBulkRequest, LeadTagsRequest, TagCreate


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = testing_session_local()
    try:
        yield db
    finally:
        db.close()


def seed_run(db: Session) -> SearchRun:
    run = SearchRun(
        niche="ERP",
        location="São Paulo",
        target_quantity=10,
        max_results=False,
        skip_without_website=True,
        validate_whatsapp=False,
        status="completed",
        message="Done",
    )
    db.add(run)
    db.flush()
    return run


def seed_lead(db: Session, run: SearchRun, name: str) -> Lead:
    lead = Lead(
        run_id=run.id,
        name=name,
        address="Av Paulista, 1000",
        phone="+5511999990000",
        website=None,
        email=f"{name.lower().replace(' ', '.')}@example.test",
    )
    db.add(lead)
    db.flush()
    return lead


def seed_tag(db: Session, name: str, color: str = "#e0f2fe") -> Tag:
    tag = Tag(name=name, color=color)
    db.add(tag)
    db.flush()
    return tag


def test_create_tag_rejects_case_insensitive_duplicate(db_session: Session) -> None:
    created = main.create_tag(TagCreate(name="Usa Bling"), db=db_session, username="test-user")

    with pytest.raises(HTTPException) as exc_info:
        main.create_tag(TagCreate(name="usa bling"), db=db_session, username="test-user")

    assert created.name == "Usa Bling"
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Já existe uma tag com esse nome."


def test_add_tags_to_lead_is_idempotent(db_session: Session) -> None:
    run = seed_run(db_session)
    lead = seed_lead(db_session, run, "Lead Alpha")
    tag = seed_tag(db_session, "Usa Bling")
    db_session.commit()

    main.add_tags_to_lead(lead.id, LeadTagsRequest(tag_ids=[tag.id]), db=db_session, username="test-user")
    result = main.add_tags_to_lead(lead.id, LeadTagsRequest(tag_ids=[tag.id]), db=db_session, username="test-user")

    associations = db_session.scalars(select(LeadTag)).all()
    assert len(associations) == 1
    assert [item.name for item in result.tags] == ["Usa Bling"]


def test_bulk_add_and_remove_tags(db_session: Session) -> None:
    run = seed_run(db_session)
    first = seed_lead(db_session, run, "Lead One")
    second = seed_lead(db_session, run, "Lead Two")
    erp = seed_tag(db_session, "Usa ERP")
    ecommerce = seed_tag(db_session, "E-commerce")
    db_session.commit()

    add_result = main.bulk_update_lead_tags(
        LeadTagsBulkRequest(lead_ids=[first.id, second.id], tag_ids=[erp.id, ecommerce.id], action="add"),
        db=db_session,
        username="test-user",
    )
    remove_result = main.bulk_update_lead_tags(
        LeadTagsBulkRequest(lead_ids=[first.id, second.id], tag_ids=[erp.id], action="remove"),
        db=db_session,
        username="test-user",
    )

    remaining_pairs = sorted((row.lead_id, row.tag_id) for row in db_session.scalars(select(LeadTag)).all())
    assert add_result.changed_associations == 4
    assert add_result.matched_leads == 2
    assert add_result.matched_tags == 2
    assert remove_result.changed_associations == 2
    assert remaining_pairs == [(first.id, ecommerce.id), (second.id, ecommerce.id)]


def test_list_leads_filters_tags_with_any_and_all(db_session: Session) -> None:
    run = seed_run(db_session)
    only_erp = seed_lead(db_session, run, "Only ERP")
    only_ecommerce = seed_lead(db_session, run, "Only Ecommerce")
    both = seed_lead(db_session, run, "Both")
    erp = seed_tag(db_session, "Usa ERP")
    ecommerce = seed_tag(db_session, "E-commerce")
    db_session.add_all(
        [
            LeadTag(lead_id=only_erp.id, tag_id=erp.id),
            LeadTag(lead_id=only_ecommerce.id, tag_id=ecommerce.id),
            LeadTag(lead_id=both.id, tag_id=erp.id),
            LeadTag(lead_id=both.id, tag_id=ecommerce.id),
        ]
    )
    db_session.commit()

    any_result = main.list_leads(tag_ids=[erp.id, ecommerce.id], tag_filter_mode="any", db=db_session, username="test-user")
    all_result = main.list_leads(tag_ids=[erp.id, ecommerce.id], tag_filter_mode="all", db=db_session, username="test-user")

    assert {lead.id for lead in any_result} == {only_erp.id, only_ecommerce.id, both.id}
    assert [lead.id for lead in all_result] == [both.id]


def test_delete_tag_removes_associations(db_session: Session) -> None:
    run = seed_run(db_session)
    first = seed_lead(db_session, run, "Lead One")
    second = seed_lead(db_session, run, "Lead Two")
    tag = seed_tag(db_session, "Remover")
    db_session.add_all([LeadTag(lead_id=first.id, tag_id=tag.id), LeadTag(lead_id=second.id, tag_id=tag.id)])
    db_session.commit()

    result = main.delete_tag(tag.id, db=db_session, username="test-user")

    assert result.deleted is True
    assert result.affected_leads == 2
    assert db_session.scalars(select(LeadTag)).all() == []
    assert db_session.get(Tag, tag.id) is None


def test_list_leads_preloads_tags_without_extra_queries(db_session: Session) -> None:
    run = seed_run(db_session)
    tag = seed_tag(db_session, "Pré-carregada")
    leads = [seed_lead(db_session, run, f"Lead {index}") for index in range(5)]
    db_session.add_all([LeadTag(lead_id=lead.id, tag_id=tag.id) for lead in leads])
    db_session.commit()

    statements: list[str] = []

    def collect_selects(*args) -> None:
        statement = str(args[2])
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", collect_selects)
    try:
        result = main.list_leads(db=db_session, username="test-user")
        select_count_after_list = len(statements)
        assert all([tag.name for tag in lead.tags] == ["Pré-carregada"] for lead in result)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", collect_selects)

    assert len(result) == 5
    assert len(statements) == select_count_after_list
    assert select_count_after_list <= 4
