"""SQLModel table imports for metadata registration."""

from assistente_medico_api.models.agent_log import AgentLogEntry
from assistente_medico_api.models.alert import Alert
from assistente_medico_api.models.conversation import Conversation, ConversationMessage
from assistente_medico_api.models.conversation_message_llm_call import ConversationMessageLlmCall
from assistente_medico_api.models.attachment import ExamAttachment
from assistente_medico_api.models.exam import Exam
from assistente_medico_api.models.patient import Patient, VitalSigns
from assistente_medico_api.models.prescription import Prescription
from assistente_medico_api.models.suggested_item import SuggestedItem

__all__ = [
    "AgentLogEntry",
    "Alert",
    "Conversation",
    "ConversationMessage",
    "ConversationMessageLlmCall",
    "ExamAttachment",
    "Exam",
    "Patient",
    "Prescription",
    "VitalSigns",
    "SuggestedItem",
]
