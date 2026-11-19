"""Independent niche registry: changes never rewrite leads or search history."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.auth import get_current_username
from backend.database import get_db
from backend.models import Niche
from backend.schemas import NicheRead, NicheWrite


router = APIRouter(prefix="/api/niches", tags=["niches"], dependencies=[Depends(get_current_username)])


def _get_niche(db: Session, niche_id: int) -> Niche:
    niche = db.get(Niche, niche_id)
    if niche is None:
        raise HTTPException(status_code=404, detail="Nicho não encontrado.")
    return niche


def _save_niche(db: Session, niche: Niche) -> Niche:
    db.add(niche)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Já existe um nicho com esse nome.") from None
    db.refresh(niche)
    return niche


@router.get("", response_model=list[NicheRead])
def list_niches(q: str = Query(default="", max_length=255), db: Session = Depends(get_db)) -> list[Niche]:
    query = select(Niche).order_by(func.lower(Niche.name), Niche.id)
    if q.strip():
        query = query.where(Niche.name.icontains(q.strip(), autoescape=True))
    return list(db.scalars(query).all())


@router.post("", response_model=NicheRead, status_code=201)
def create_niche(payload: NicheWrite, db: Session = Depends(get_db)) -> Niche:
    return _save_niche(db, Niche(name=payload.name))


@router.get("/{niche_id}", response_model=NicheRead)
def get_niche(niche_id: int, db: Session = Depends(get_db)) -> Niche:
    return _get_niche(db, niche_id)


@router.patch("/{niche_id}", response_model=NicheRead)
def update_niche(niche_id: int, payload: NicheWrite, db: Session = Depends(get_db)) -> Niche:
    niche = _get_niche(db, niche_id)
    niche.name = payload.name
    return _save_niche(db, niche)


@router.delete("/{niche_id}")
def delete_niche(niche_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    db.delete(_get_niche(db, niche_id))
    db.commit()
    return {"deleted": True}
