from fastapi import APIRouter, Depends

from app.api import (
    boxes,
    contributions,
    expenses,
    funds,
    inventory,
    partners,
    pricing,
    purchases,
    rates,
    reports,
    sales,
    settlements,
    transfers,
)
from app.api.deps import require_api_key

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])
for module in (
    partners,
    rates,
    purchases,
    sales,
    inventory,
    expenses,
    pricing,
    boxes,
    settlements,
    contributions,
    transfers,
    funds,
    reports,
):
    router.include_router(module.router)
