"""In-memory protocol mapping by CID code."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ProtocolSuggestedTemplate:
    type: str
    description: str


@dataclass(slots=True)
class ProtocolResult:
    protocol_ref: str
    exams: list[str]
    suggested_actions: list[ProtocolSuggestedTemplate]
    drug_interaction_alert: bool = False


PROTOCOL_MAP: dict[str, ProtocolResult] = {
    "L40.5": ProtocolResult(
        protocol_ref="PCDT Artrite Psoriásica - CONITEC 2023",
        exams=[
            "Hemograma completo",
            "Contagem de plaquetas",
            "Creatinina sérica",
            "AST/TGO",
            "ALT/TGP",
        ],
        suggested_actions=[
            ProtocolSuggestedTemplate(type="exam", description="Solicitar Hemograma completo"),
            ProtocolSuggestedTemplate(type="exam", description="Solicitar Contagem de plaquetas"),
            ProtocolSuggestedTemplate(type="exam", description="Solicitar Creatinina sérica"),
            ProtocolSuggestedTemplate(type="exam", description="Solicitar AST/TGO"),
            ProtocolSuggestedTemplate(type="exam", description="Solicitar ALT/TGP"),
            ProtocolSuggestedTemplate(type="observation", description="Avaliar acometimento cutâneo (PASI)"),
            ProtocolSuggestedTemplate(type="review", description="Reavaliação em 24h"),
        ],
    ),
    "A41.9": ProtocolResult(
        protocol_ref="Protocolo de Sepse - MS 2019",
        exams=[
            "Hemoculturas (2 amostras)",
            "Lactato sérico",
            "Hemograma completo",
            "PCR e Procalcitonina",
            "Gasometria arterial",
            "Creatinina e Ureia",
        ],
        suggested_actions=[
            ProtocolSuggestedTemplate(
                type="prescription",
                description="Antibioticoterapia empírica em até 1h (ver protocolo)",
            ),
            ProtocolSuggestedTemplate(
                type="exam",
                description="Coletar hemoculturas antes dos antibióticos",
            ),
            ProtocolSuggestedTemplate(
                type="observation",
                description="Monitorar sinais de disfunção orgânica",
            ),
            ProtocolSuggestedTemplate(
                type="review",
                description="Reavaliação em 6h - bundle de sepse",
            ),
        ],
    ),
    "T81.4": ProtocolResult(
        protocol_ref="Protocolo Pós-Cirúrgico - Controle de Infecção",
        exams=[
            "Hemograma completo",
            "PCR",
            "Cultura de sítio cirúrgico",
            "Glicemia",
        ],
        suggested_actions=[
            ProtocolSuggestedTemplate(
                type="prescription",
                description="Verificar interação: antibiótico + anticoagulante em uso",
            ),
            ProtocolSuggestedTemplate(type="exam", description="Solicitar cultura de sítio cirúrgico"),
            ProtocolSuggestedTemplate(type="observation", description="Inspecionar ferida operatória"),
        ],
        drug_interaction_alert=True,
    ),
    "M05.3": ProtocolResult(
        protocol_ref="Diretriz Artrite Reumatoide - CFM/MS (referência mock)",
        exams=[
            "Hemograma completo",
            "PCR (ves)",
            "Fator reumatoide e anti-CCP",
            "Função hepática (TGO/TGP)",
            "Creatinina",
        ],
        suggested_actions=[
            ProtocolSuggestedTemplate(type="exam", description="Solicitar PCR e autoanticorpos"),
            ProtocolSuggestedTemplate(type="exam", description="Avaliar marcadores de atividade de doença"),
            ProtocolSuggestedTemplate(
                type="prescription",
                description="Avaliar dmard de acordo com protocolo institucional",
            ),
            ProtocolSuggestedTemplate(type="review", description="Reavaliação ambulatorial em 4-8 semanas"),
        ],
    ),
}

DEFAULT_PROTOCOL = ProtocolResult(
    protocol_ref="Protocolo institucional genérico (mock)",
    exams=["Hemograma completo", "Creatinina sérica"],
    suggested_actions=[
        ProtocolSuggestedTemplate(
            type="exam", description="Solicitar exames basais conforme protocolo"
        ),
        ProtocolSuggestedTemplate(type="review", description="Reavaliação clínica em 24-48h"),
    ],
)


def get_protocol_for_cid(code: str) -> ProtocolResult:
    return PROTOCOL_MAP.get(code, DEFAULT_PROTOCOL)
