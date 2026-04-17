"""SQLModel table imports for metadata registration."""

from assistente_medico_api.models.agent_log import AgentLogEntry
from assistente_medico_api.models.alert import Alert
from assistente_medico_api.models.attachment import ExamAttachment
from assistente_medico_api.models.exam import Exam
from assistente_medico_api.models.patient import Patient, VitalSigns
from assistente_medico_api.models.suggested_item import SuggestedItem

__all__ = [
    "AgentLogEntry",
    "Alert",
    "ExamAttachment",
    "Exam",
    "Patient",
    "VitalSigns",
    "SuggestedItem",
]
