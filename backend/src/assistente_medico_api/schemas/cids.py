"""Schemas for CID catalog endpoint."""

from pydantic import BaseModel


class Cid(BaseModel):
    code: str
    label: str


class CidListResponse(BaseModel):
    cids: list[Cid]
