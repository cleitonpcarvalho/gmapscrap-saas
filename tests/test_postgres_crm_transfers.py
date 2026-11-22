"""Real PostgreSQL regressions for populated CRM deletion and atomic transfer."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from threading import Event

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend import main, manual_crm
from backend.auth import COOKIE_NAME, create_session_token
from backend.config import get_settings
from backend.database import get_db
from backend.models import CrmActivity, CrmFollowUp, CrmFunnel, CrmFunnelStage, CrmLead, CrmStageHistory, Lead
from backend.services.crm_transfers import delete_pipeline
from test_postgres_crm_security import PHASE1, SECURITY, data_snapshot, postgres, run_script

pytestmark = pytest.mark.postgres


@pytest.fixture()
def crm(postgres):
    run_script(postgres, PHASE1)
    run_script(postgres, SECURITY)
    with Session(postgres) as db:
        source = CrmFunnel(name="Origem")
        target = CrmFunnel(name="Destino")
        other = CrmFunnel(name="Outro negócio")
        db.add_all([source,target,other]);db.flush()
        stages = [
            CrmFunnelStage(funnel=source,key="new",label="Novo",position=0),
            CrmFunnelStage(funnel=source,key="qualified",label="Qualificado",position=1,is_won=True),
            CrmFunnelStage(funnel=source,key="custom",label="Especial",position=2),
            CrmFunnelStage(funnel=target,key="new",label="Entrada",position=0),
            CrmFunnelStage(funnel=target,key="qualified",label="Proposta",position=1,is_won=True),
            CrmFunnelStage(funnel=other,key="new",label="Outro contato",position=0),
        ]
        db.add_all(stages);db.flush()
        leads = db.scalars(select(Lead).order_by(Lead.id)).all()
        closed = datetime(2026,11,20,15,0,tzinfo=timezone.utc)
        cards = [
            CrmLead(lead_id=leads[0].id,funnel=source,stage_ref=stages[0],stage="new",position=0,managed_manually=True,sales_outcome="open",qualification_notes="Nota histórica A",estimated_value=Decimal("1234.56"),currency="USD"),
            CrmLead(lead_id=leads[1].id,funnel=source,stage_ref=stages[0],stage="new",position=4,qualification_notes="Nota histórica B"),
            CrmLead(lead_id=leads[2].id,funnel=source,stage_ref=stages[1],stage="qualified",position=7,managed_manually=True,sales_outcome="won",estimated_value=Decimal("500.00"),currency="EUR",closed_at=closed),
            CrmLead(lead_id=leads[3].id,funnel=source,stage_ref=stages[2],stage="custom",position=0,managed_manually=True,sales_outcome="lost",lost_reason="Sem orçamento",closed_at=closed),
            CrmLead(lead_id=leads[9].id,funnel=target,stage_ref=stages[3],stage="new",position=8,qualification_notes="Negócio do destino"),
            CrmLead(lead_id=leads[10].id,funnel=target,stage_ref=stages[4],stage="qualified",position=3),
            CrmLead(lead_id=leads[0].id,funnel=other,stage_ref=stages[5],stage="new",position=0,managed_manually=True,sales_outcome="open",qualification_notes="Negócio independente"),
        ]
        db.add_all(cards);db.flush()
        for item in cards[:4]:
            db.add(CrmStageHistory(crm_lead_id=item.id,from_stage="historical",to_stage=item.stage,to_stage_id=item.stage_id,changed_by="ai"))
        for item in [cards[0],cards[2],cards[3]]:
            db.add(CrmActivity(crm_lead_id=item.id,kind="note",body=f"Nota imutável {item.id}",actor="original",created_at=closed))
            db.add(CrmFollowUp(crm_lead_id=item.id,title=f"Retornar {item.id}",due_at=datetime(2026,12,1,12,tzinfo=timezone.utc)))
        db.commit()
        values={"source":source.id,"target":target.id,"other":other.id,
                "stages":[s.id for s in stages],"cards":[c.id for c in cards]}
    app = FastAPI()
    app.add_api_route('/api/crm/funnels/{funnel_id}',main.delete_crm_funnel,methods=['DELETE'])
    app.add_api_route('/api/crm/funnels/{funnel_id}/stages/{stage_id}',main.delete_crm_funnel_stage,methods=['DELETE'])
    app.include_router(manual_crm.router)
    def local_db():
        with Session(postgres) as db:yield db
    app.dependency_overrides[get_db]=local_db
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME,create_session_token(get_settings().app_username))
        yield {**values,"engine":postgres,"client":client}


def rows(engine,table):
    with engine.connect() as c:
        return {row['id']:dict(row) for row in c.execute(text(f'SELECT * FROM public.{table} ORDER BY id')).mappings()}


def assert_history_preserved(before,after,deleted_stage_ids):
    assert before.keys() <= after.keys()
    for key,old in before.items():
        expected=dict(old)
        for field in ['from_stage_id','to_stage_id']:
            if old[field] in deleted_stage_ids:expected[field]=None
        assert after[key]==expected


def assert_commercial_fields_preserved(before,after,ids):
    mutable={'funnel_id','stage_id','stage','position','version','updated_at'}
    assert before.keys()==after.keys()
    for key,old in before.items():
        if key not in ids:assert after[key]==old
        else:
            assert {k:v for k,v in old.items() if k not in mutable} == {k:v for k,v in after[key].items() if k not in mutable}
            assert after[key]['version']==old['version']+1


def unchanged_shared_tables(before,after):
    for table in ['leads','search_runs','niches','tags','lead_tags','crm_follow_ups','whatsapp_messages','whatsapp_conversations']:
        assert after[table]==before[table],table


@pytest.mark.parametrize('kind',['stage','pipeline'])
def test_populated_transfer_preserves_cards_notes_history_followups_and_sales(crm,kind):
    e,c=crm['engine'],crm['client']
    before=data_snapshot(e)
    cards_before,history_before,activities_before=rows(e,'crm_leads'),rows(e,'crm_stage_history'),rows(e,'crm_activities')
    if kind=='stage':
        path=f"/api/crm/funnels/{crm['source']}/stages/{crm['stages'][0]}?move_to_stage_id={crm['stages'][1]}"
        moved=crm['cards'][:2];deleted={crm['stages'][0]}
    else:
        path=f"/api/crm/funnels/{crm['source']}?move_to_funnel_id={crm['target']}"
        moved=crm['cards'][:4];deleted=set(crm['stages'][:3])
    response=c.delete(path)
    assert response.status_code==200,response.text
    assert response.json()=={'status':'ok','moved_cards':len(moved)}
    after=data_snapshot(e)
    current,history,activities=rows(e,'crm_leads'),rows(e,'crm_stage_history'),rows(e,'crm_activities')
    assert_commercial_fields_preserved(cards_before,current,moved)
    assert_history_preserved(history_before,history,deleted)
    assert len(history)==len(history_before)+len(moved)
    assert all(activities[key]==value for key,value in activities_before.items())
    assert len(activities)==len(activities_before)+(1 if kind=='stage' else 3)
    unchanged_shared_tables(before,after)
    if kind=='stage':
        for card_id,position in zip(moved,[8,9]):
            assert current[card_id]['stage_id']==crm['stages'][1]
            assert current[card_id]['funnel_id']==crm['source']
            assert current[card_id]['position']==position
        assert crm['source'] in rows(e,'crm_funnels')
    else:
        expected=[(crm['stages'][3],9),(crm['stages'][3],10),(crm['stages'][4],4),(crm['stages'][3],11)]
        for card_id,(stage_id,position) in zip(moved,expected):
            assert current[card_id]['funnel_id']==crm['target']
            assert current[card_id]['stage_id']==stage_id and current[card_id]['position']==position
        assert crm['source'] not in rows(e,'crm_funnels')
    assert deleted.isdisjoint(rows(e,'crm_funnel_stages'))
    detail=c.get(f"/api/crm/manual/cards/{moved[0]}").json()
    assert detail['qualification_notes']=='Nota histórica A'
    assert any(item['actor']=='original' for item in detail['activities'])
    transfer=next(item for item in detail['activities'] if item['actor']==get_settings().app_username)
    assert transfer['details']['from_funnel']['id']==crm['source']
    assert transfer['details']['from_stage']['id']==crm['stages'][0]
    # A form loaded before the transfer cannot overwrite its new membership.
    stale=c.patch(f"/api/crm/manual/cards/{moved[0]}",json={'version':cards_before[moved[0]]['version'],'estimated_value':'1.00'})
    assert stale.status_code==409
    assert c.post(f"/api/crm/manual/cards/{moved[0]}/activities",json={'kind':'call','body':'Contato após transferência'}).status_code==201
    follow=detail['follow_ups'][0]
    assert c.patch(f"/api/crm/manual/follow-ups/{follow['id']}",json={'version':follow['version'],'action':'complete'}).status_code==200


def test_preloaded_relationships_are_updated_before_parent_deletion(crm):
    e=crm['engine']
    with Session(e,expire_on_commit=False) as db:
        pipeline=db.get(CrmFunnel,crm['source'])
        stage=db.get(CrmFunnelStage,crm['stages'][0])
        old_cards=list(stage.crm_leads)
        assert len(old_cards)==2 and len(pipeline.crm_leads)==4
        main.delete_crm_funnel_stage(pipeline.id,stage.id,crm['stages'][1],db=db,username='preloaded-test')
        assert not stage.crm_leads
        assert all(card.stage_ref.id==crm['stages'][1] for card in old_cards)
        main.delete_crm_funnel(pipeline.id,crm['target'],db=db,username='preloaded-test')
        assert not pipeline.crm_leads
        assert db.get(CrmFunnel,pipeline.id) is None
        assert all(card.funnel.id==crm['target'] for card in old_cards)
    assert len(rows(e,'crm_leads'))==16


def test_duplicate_destination_membership_rejects_entire_transfer_without_merging(crm):
    e=crm['engine']
    with Session(e) as db:
        source=db.get(CrmLead,crm['cards'][1])
        db.add(CrmLead(lead_id=source.lead_id,funnel_id=crm['target'],stage_id=crm['stages'][3],stage='new',position=99,qualification_notes='Outro negócio com histórico próprio'))
        db.commit()
    before=data_snapshot(e)
    response=crm['client'].delete(f"/api/crm/funnels/{crm['source']}?move_to_funnel_id={crm['target']}")
    assert response.status_code==409 and 'já têm card' in response.json()['detail']
    assert data_snapshot(e)==before


@pytest.mark.parametrize('kind',['stage','pipeline'])
def test_failure_after_cards_are_flushed_rolls_back_moves_history_and_parent_deletion(crm,kind):
    e=crm['engine'];before=data_snapshot(e)
    model=CrmFunnelStage if kind=='stage' else CrmFunnel
    target_id=crm['stages'][0] if kind=='stage' else crm['source']
    def fail(mapper,connection,target):
        if target.id==target_id:raise RuntimeError('injected failure after transfer flush')
    event.listen(model,'before_delete',fail)
    try:
        path=(f"/api/crm/funnels/{crm['source']}/stages/{target_id}?move_to_stage_id={crm['stages'][1]}" if kind=='stage'
              else f"/api/crm/funnels/{target_id}?move_to_funnel_id={crm['target']}")
        with pytest.raises(RuntimeError,match='injected failure'):
            crm['client'].delete(path)
        assert data_snapshot(e)==before
    finally:event.remove(model,'before_delete',fail)


def test_late_unique_conflict_returns_409_and_rolls_back_every_prepared_move(crm):
    e=crm['engine'];before=data_snapshot(e);fired=[]
    def conflict(session,flush_context,instances):
        for card in session.dirty:
            if isinstance(card,CrmLead) and card.id==crm['cards'][0] and card.funnel.id==crm['target'] and not fired:
                fired.append(True)
                session.connection().execute(text("INSERT INTO crm_leads(lead_id,funnel_id,stage_id,stage,position) VALUES (:lead,:funnel,:stage,'new',999)"),{'lead':card.lead_id,'funnel':crm['target'],'stage':crm['stages'][3]})
                break
    event.listen(Session,'before_flush',conflict)
    try:
        response=crm['client'].delete(f"/api/crm/funnels/{crm['source']}?move_to_funnel_id={crm['target']}")
        assert fired and response.status_code==409,response.text
        assert data_snapshot(e)==before
    finally:event.remove(Session,'before_flush',conflict)


@pytest.mark.parametrize('kind,destination,status',[
    ('stage',None,409),('stage','same',422),('stage','other-pipeline',404),('stage','missing',404),
    ('pipeline',None,409),('pipeline','same',422),('pipeline','missing',404),
])
def test_invalid_destinations_leave_all_records_unchanged(crm,kind,destination,status):
    before=data_snapshot(crm['engine'])
    if kind=='stage':
        path=f"/api/crm/funnels/{crm['source']}/stages/{crm['stages'][0]}"
        value={'same':crm['stages'][0],'other-pipeline':crm['stages'][3],'missing':999999}.get(destination)
        if value is not None:path+=f'?move_to_stage_id={value}'
    else:
        path=f"/api/crm/funnels/{crm['source']}"
        value={'same':crm['source'],'missing':999999}.get(destination)
        if value is not None:path+=f'?move_to_funnel_id={value}'
    assert crm['client'].delete(path).status_code==status
    assert data_snapshot(crm['engine'])==before


def test_default_pipeline_and_last_stage_cannot_be_deleted(crm):
    before=data_snapshot(crm['engine'])
    assert crm['client'].delete('/api/crm/funnels/1').status_code==409
    assert crm['client'].delete(f"/api/crm/funnels/{crm['other']}/stages/{crm['stages'][5]}").status_code==409
    assert data_snapshot(crm['engine'])==before


def test_destination_without_stages_rejects_the_whole_transfer(crm):
    e=crm['engine']
    with Session(e) as db:
        empty=CrmFunnel(name='Destino sem estágios');db.add(empty);db.commit();empty_id=empty.id
    before=data_snapshot(e)
    response=crm['client'].delete(f"/api/crm/funnels/{crm['source']}?move_to_funnel_id={empty_id}")
    assert response.status_code==409 and 'sem estágios' in response.json()['detail']
    assert data_snapshot(e)==before


def test_lock_timeout_returns_retryable_409_and_leaves_session_usable(crm):
    e=crm['engine'];before=data_snapshot(e)
    with e.begin() as blocker:
        blocker.execute(text('SELECT id FROM crm_funnels WHERE id=:id FOR UPDATE'),{'id':crm['source']})
        with Session(e) as db:
            db.execute(text("SET LOCAL lock_timeout='150ms'"))
            with pytest.raises(HTTPException) as error:
                main.delete_crm_funnel(crm['source'],crm['target'],db=db,username='lock-test')
            assert error.value.status_code==409
            assert db.scalar(text('SELECT 1'))==1
    assert data_snapshot(e)==before


def test_pipeline_locks_prevent_new_membership_during_transfer(crm):
    e=crm['engine'];ready,release=Event(),Event()
    def pause(session,flush_context,instances):
        if any(isinstance(item,CrmFunnel) and item.id==crm['source'] for item in session.deleted):
            ready.set()
            assert release.wait(5),'test transfer release timed out'
    def transfer():
        with Session(e) as db:return delete_pipeline(db,crm['source'],crm['target'],actor='concurrent-test')
    event.listen(Session,'before_flush',pause)
    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            future=workers.submit(transfer)
            try:
                assert ready.wait(5),'transfer did not reach deletion'
                with pytest.raises(DBAPIError) as error:
                    with e.begin() as c:
                        c.exec_driver_sql("SET LOCAL lock_timeout='150ms'")
                        c.execute(text("INSERT INTO crm_leads(lead_id,funnel_id,stage_id,stage) VALUES (12,:funnel,:stage,'new')"),{'funnel':crm['target'],'stage':crm['stages'][3]})
                assert error.value.orig.sqlstate=='55P03'
            finally:release.set()
            assert future.result(timeout=5)==4
        assert crm['source'] not in rows(e,'crm_funnels')
        assert len(rows(e,'crm_leads'))==16
    finally:
        release.set();event.remove(Session,'before_flush',pause)
