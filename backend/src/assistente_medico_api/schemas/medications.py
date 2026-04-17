"""Schemas for medication catalog endpoint."""

from pydantic import BaseModel, ConfigDict, Field


class MedicationOption(BaseModel):
    """Medication option exposed to form pickers."""

    model_config = ConfigDict(populate_by_name=True)

    code: str
    label: str
    active_ingredient: str = Field(alias="activeIngredient")
    source_tags: list[str] = Field(default_factory=list, alias="sourceTags")


class MedicationListResponse(BaseModel):
    """Response model for medication list endpoint."""

    medications: list[MedicationOption]
