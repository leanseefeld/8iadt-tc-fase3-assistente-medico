"""Schemas for suggested item resources."""

from pydantic import BaseModel, ConfigDict, Field


class SuggestedItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    type: str
    description: str
    status: str
    protocol_ref: str | None = Field(default=None, alias="protocolRef")


class SuggestedItemCreateRequest(BaseModel):
    type: str
    description: str


class SuggestedItemPatchRequest(BaseModel):
    status: str | None = None
    description: str | None = None


class SuggestedItemResponse(BaseModel):
    item: SuggestedItem
