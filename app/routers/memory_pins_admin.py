"""Admin settings > Inference > Memory pinning (services/memory_pins.py)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas.memory_pins import PinNode, PinOverview, PinUnload, PinUpdate
from app.services.auth_service import require_admin
from app.services.memory_pins import MemoryPinsError, MemoryPinsService

router = APIRouter(prefix="/api/settings/memory-pins", tags=["memory-pins"])


@router.get("", response_model=PinOverview)
async def get_memory_pins(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)) -> PinOverview:
    return await MemoryPinsService(db).overview()


@router.put("", response_model=PinNode)
async def set_memory_pins(
    body: PinUpdate, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> PinNode:
    try:
        return await MemoryPinsService(db).set_pins(body.address, body.pinned_models)
    except MemoryPinsError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.post("/unload", response_model=PinNode)
async def unload_model(
    body: PinUnload, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> PinNode:
    try:
        return await MemoryPinsService(db).unload(body.address, body.tag)
    except MemoryPinsError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
