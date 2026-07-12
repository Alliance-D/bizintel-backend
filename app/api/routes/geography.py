from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.geography_service import list_cells, list_districts, list_sectors

router = APIRouter()


@router.get("/districts")
def districts(db: Session = Depends(get_db)) -> dict:
    """List Kigali districts for the location pickers."""
    return {"districts": list_districts(db)}


@router.get("/sectors")
def sectors(district: str = Query(...), db: Session = Depends(get_db)) -> dict:
    """List the sectors within a district."""
    return {"district": district, "sectors": list_sectors(db, district)}


@router.get("/cells")
def cells(district: str = Query(...), sector: str = Query(...), db: Session = Depends(get_db)) -> dict:
    """List the cells within a district and sector."""
    return {"district": district, "sector": sector, "cells": list_cells(db, district, sector)}
