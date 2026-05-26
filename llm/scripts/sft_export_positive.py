"""
Lógica de exportação SFT (truncamento, funil, montagem de linhas JSONL).

Importado pelo notebook export-positive-conversations.ipynb.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pandas as pd

GUARDRAIL_TOXIC = frozenset({"blocked", "regenerated"})


def _normalized_guardrail(status: str | None) -> str:
    s = (status or "").strip().lower()
    return s if s else "safe"


def is_toxic_assistant_turn(row: pd.Series) -> bool:
    if row.get("author") != "assistant":
        return False
    if row.get("feedback_rating") == "negative":
        return True
    return _normalized_guardrail(row.get("guardrail_status")) in GUARDRAIL_TOXIC


def find_last_positive_index(messages: pd.DataFrame) -> int | None:
    """Índice da última mensagem assistant com feedback positive."""
    idx: int | None = None
    for i, row in messages.iterrows():
        if row.get("author") == "assistant" and row.get("feedback_rating") == "positive":
            idx = i
    return idx


def has_toxic_before(messages: pd.DataFrame, last_pos_idx: int) -> bool:
    for i, row in messages.iloc[:last_pos_idx].iterrows():
        if is_toxic_assistant_turn(row):
            return True
    return False


def message_count_in_prefix(messages: pd.DataFrame, last_pos_idx: int) -> int:
    prefix = messages.iloc[: last_pos_idx + 1]
    return int((prefix["author"].isin(["user", "assistant"])).sum())


def turn_count_in_prefix(messages: pd.DataFrame, last_pos_idx: int) -> int:
    """Turnos completos (pergunta user + resposta assistant) no prefixo exportado."""
    prefix = messages.iloc[: last_pos_idx + 1]
    users = int((prefix["author"] == "user").sum())
    assistants = int((prefix["author"] == "assistant").sum())
    return min(users, assistants)


@dataclass
class ConversationExportTarget:
    conversation_id: str
    patient_id: str
    doctor_id: str
    patient_name: str
    message_id: str
    llm_input: list[dict[str, Any]]
    llm_output: str
    message_count: int
    turn_count: int


def evaluate_conversation(
    conv_id: str,
    group: pd.DataFrame,
) -> tuple[ConversationExportTarget | None, str | None]:
    """
    Avalia uma conversa; retorna (target, None) ou (None, drop_reason).
    """
    messages = group.sort_values("created_at").reset_index(drop=True)
    last_idx = find_last_positive_index(messages)
    if last_idx is None:
        return None, "no_positive"

    last_row = messages.iloc[last_idx]
    if has_toxic_before(messages, last_idx):
        return None, "toxic_before_last_positive"
    if is_toxic_assistant_turn(last_row):
        return None, "toxic_final_turn"

    llm_input = last_row.get("llm_input")
    llm_output = last_row.get("llm_output")
    if llm_input is None or llm_output is None:
        return None, "missing_llm_pair"

    if isinstance(llm_input, str):
        llm_input = json.loads(llm_input)

    return (
        ConversationExportTarget(
            conversation_id=str(conv_id),
            patient_id=str(last_row["patient_id"]),
            doctor_id=str(last_row["doctor_id"]),
            patient_name=str(last_row.get("patient_name") or ""),
            message_id=str(last_row["id"]),
            llm_input=list(llm_input),
            llm_output=str(llm_output),
            message_count=message_count_in_prefix(messages, last_idx),
            turn_count=turn_count_in_prefix(messages, last_idx),
        ),
        None,
    )


def build_export_rows(
    targets: list[ConversationExportTarget],
    aux_df: pd.DataFrame,
    *,
    salt: str,
    pseudonymize_fn,
) -> list[dict[str, Any]]:
    """Monta linhas JSONL (generate + aux) com IDs pseudonimizados (pré-anonimização de texto)."""
    aux_by_msg: dict[str, list[pd.Series]] = {}
    if not aux_df.empty:
        for msg_id, grp in aux_df.groupby("assistant_message_id"):
            aux_by_msg[str(msg_id)] = [
                grp.sort_values("sequence").iloc[i] for i in range(len(grp))
            ]

    rows: list[dict[str, Any]] = []
    for t in targets:
        conv_p = pseudonymize_fn(t.conversation_id, "conv", salt)
        pt_p = pseudonymize_fn(t.patient_id, "pt", salt)
        dr_p = pseudonymize_fn(t.doctor_id, "dr", salt)
        msg_p = pseudonymize_fn(t.message_id, "msg", salt)

        rows.append(
            {
                "conversation_id": conv_p,
                "patient_id": pt_p,
                "doctor_id": dr_p,
                "message_id": msg_p,
                "call_type": "generate",
                "sequence": -1,
                "model": None,
                "llm_input": t.llm_input,
                "llm_output": t.llm_output,
                "_raw_conversation_id": t.conversation_id,
                "_raw_patient_id": t.patient_id,
                "_raw_message_id": t.message_id,
                "_patient_name": t.patient_name,
                "_message_count": t.message_count,
                "_turn_count": t.turn_count,
            }
        )

        for aux in aux_by_msg.get(t.message_id, []):
            aux_input = aux["llm_input"]
            if isinstance(aux_input, str):
                aux_input = json.loads(aux_input)
            rows.append(
                {
                    "conversation_id": conv_p,
                    "patient_id": pt_p,
                    "doctor_id": dr_p,
                    "message_id": msg_p,
                    "call_type": str(aux["call_type"]),
                    "sequence": int(aux["sequence"]),
                    "model": aux.get("model"),
                    "llm_input": list(aux_input),
                    "llm_output": str(aux["llm_output"]),
                    "_raw_conversation_id": t.conversation_id,
                    "_raw_patient_id": t.patient_id,
                    "_raw_message_id": t.message_id,
                    "_patient_name": t.patient_name,
                    "_message_count": t.message_count,
                    "_turn_count": t.turn_count,
                }
            )
    return rows
