from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.geography_service import list_cells, list_districts, list_sectors

router = APIRouter()


@router.get("/districts")
def districts(db: Session = Depends(get_db)) -> dict:
    return {"districts": list_districts(db)}


@router.get("/sectors")
def sectors(district: str = Query(...), db: Session = Depends(get_db)) -> dict:
    return {"district": district, "sectors": list_sectors(db, district)}


@router.get("/cells")
def cells(district: str = Query(...), sector: str = Query(...), db: Session = Depends(get_db)) -> dict:
    return {"district": district, "sector": sector, "cells": list_cells(db, district, sector)}
