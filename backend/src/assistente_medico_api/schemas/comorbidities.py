"""Comorbidities reference data schemas."""

from pydantic import BaseModel, ConfigDict, Field


class ComorbidityOption(BaseModel):
    """Comorbidity option for patient check-in."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "code": "HAS",
                "label": "Hipertensão Arterial Sistêmica",
                "category": "cardiovascular",
            }
        }
    )

    code: str = Field(..., description="Short identifier for comorbidity (e.g., 'HAS', 'DM2')")
    label: str = Field(..., description="Full display name in Portuguese")
    category: str = Field(
        default="other",
        description="Category for grouping (e.g., 'cardiovascular', 'endocrine', 'respiratory')",
    )


class ComorbidititiesResponse(BaseModel):
    """Response containing available comorbidity options."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "comorbidities": [
                    {
                        "code": "HAS",
                        "label": "Hipertensão Arterial Sistêmica",
                        "category": "cardiovascular",
                    },
                    {
                        "code": "DM2",
                        "label": "Diabetes Mellitus Tipo 2",
                        "category": "endocrine",
                    },
                ]
            }
        }
    )

    comorbidities: list[ComorbidityOption] = Field(
        ..., description="Available comorbidity options for patient selection"
    )
