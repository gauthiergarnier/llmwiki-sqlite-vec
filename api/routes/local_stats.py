"""Local index-stats route — thin HTTP layer, delegates to services/stats.py."""

from fastapi import APIRouter, Depends, Request

from deps import get_user_id
from services.stats import get_index_stats

router = APIRouter(tags=["stats"])


@router.get("/v1/index-stats")
async def index_stats(
    user_id: str = Depends(get_user_id),
    request: Request = None,
):
    db = request.app.state.sqlite_db
    return await get_index_stats(db, user_id)
