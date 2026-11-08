"""The HTTP side of image_gen_ring.py: refuses image actions with 409 while a ring does not allow them."""

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.image_gen_ring import LOCAL_REFUSED, LOOPBACK_REFUSED, REASON, image_gen_ring, is_loopback


async def image_gen_on(db: AsyncSession = Depends(get_db)) -> None:
    """Image requests: refused while image generation is off (a ring in local mode)."""
    if await image_gen_ring.is_off(db):
        raise HTTPException(status_code=409, detail=REASON)


async def no_local_in_ring(db: AsyncSession = Depends(get_db)) -> None:
    """Starting or installing a local engine: refused in any ring (only remote mode there)."""
    if await image_gen_ring.in_ring(db):
        raise HTTPException(status_code=409, detail=LOCAL_REFUSED)


async def refuse_loopback_in_ring(db: AsyncSession, mode: str, hosts: list[str]) -> None:
    """Saving Remote in a ring: every address must be one every pAIring server reaches (not localhost)."""
    if mode == "remote" and any(is_loopback(h) for h in hosts) and await image_gen_ring.in_ring(db):
        raise HTTPException(status_code=409, detail=LOOPBACK_REFUSED)
