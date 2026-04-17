"""CID catalog endpoint."""

from fastapi import APIRouter

from assistente_medico_api.schemas.cids import CidListResponse
from assistente_medico_api.services.cid_catalog import list_cids

router = APIRouter(tags=["patients"])


@router.get("/cids", response_model=CidListResponse)
async def get_cids() -> CidListResponse:
    return CidListResponse(cids=list_cids())
