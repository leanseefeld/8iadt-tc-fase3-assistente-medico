"""Comorbidities endpoint."""

from fastapi import APIRouter

from assistente_medico_api.schemas.comorbidities import (
    ComorbidityOption,
    ComorbidititiesResponse,
)

router = APIRouter(prefix="/assistant", tags=["comorbidities"])

# Reference data: Comorbidities expanded list including pregnancy
_COMORBIDITIES = [
    ComorbidityOption(
        code="HAS", label="Hipertensão Arterial Sistêmica", category="cardiovascular"
    ),
    ComorbidityOption(code="DM2", label="Diabetes Mellitus Tipo 2", category="endocrine"),
    ComorbidityOption(code="DM1", label="Diabetes Mellitus Tipo 1", category="endocrine"),
    ComorbidityOption(code="IRC", label="Insuficiência Renal Crônica", category="renal"),
    ComorbidityOption(
        code="DRC-Dialise", label="Doença Renal Crônica em Diálise", category="renal"
    ),
    ComorbidityOption(
        code="IC", label="Insuficiência Cardíaca", category="cardiovascular"
    ),
    ComorbidityOption(
        code="DAC", label="Doença Arterial Coronariana", category="cardiovascular"
    ),
    ComorbidityOption(
        code="AVC-Previo", label="Acidente Vascular Cerebral Prévio", category="neurological"
    ),
    ComorbidityOption(code="FAi", label="Fibrilação Atrial", category="cardiovascular"),
    ComorbidityOption(code="Asma", label="Asma", category="respiratory"),
    ComorbidityOption(
        code="DPOC", label="Doença Pulmonar Obstrutiva Crônica", category="respiratory"
    ),
    ComorbidityOption(code="Obesidade", label="Obesidade", category="metabolic"),
    ComorbidityOption(
        code="Hepatopatia", label="Doença Hepática Crônica", category="hepatic"
    ),
    ComorbidityOption(
        code="Autoimune", label="Doença Autoimune", category="immunological"
    ),
    ComorbidityOption(
        code="Imunossuprimido", label="Imunossupressão", category="immunological"
    ),
    ComorbidityOption(code="HIV", label="HIV", category="infectious"),
    ComorbidityOption(code="Cancer", label="Câncer Ativo", category="oncological"),
    ComorbidityOption(code="Tabagismo", label="Tabagismo", category="behavioral"),
    ComorbidityOption(code="Etilismo", label="Etilismo Crônico", category="behavioral"),
    ComorbidityOption(code="Gravidez", label="Gravidez", category="reproductive"),
    ComorbidityOption(code="Puerperio", label="Puerpério", category="reproductive"),
    ComorbidityOption(code="Outras", label="Outras Comorbidades", category="other"),
]


@router.get(
    "/comorbidities",
    response_model=ComorbidititiesResponse,
    summary="Get available comorbidity options",
    description="Returns available comorbidity options for patient check-in selection.",
)
async def get_comorbidities() -> ComorbidititiesResponse:
    """
    Get comorbidities endpoint.

    Returns a list of available comorbidities for patient selection.
    This is read-only reference data stored in memory.

    Returns:
        ComorbidititiesResponse: Response object containing comorbidities list
    """
    return ComorbidititiesResponse(comorbidities=_COMORBIDITIES)
