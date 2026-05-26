"""Script one-shot para gerar JSONL SFT (usado para validar pipeline antes do notebook)."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "llm" / "scripts"))

from sft_anonymize import (  # noqa: E402
    ExportFunnel,
    ReplacementRegistry,
    anonymize_sft_text,
    assign_fake_name,
    build_clinical_allow_list,
    pseudonymize_id,
    validate_anonymization,
)
from sft_export_positive import build_export_rows, evaluate_conversation  # noqa: E402

SALT = "sft-export-dev"
DB_PATH = _REPO / "backend" / "assistente_medico.db"
OUTPUT_PATH = _REPO / "llm" / "fine-tuning" / "assets" / "sft_positive_conversations.jsonl"


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    msgs = pd.read_sql_query(
        """
        SELECT m.*, c.patient_id, c.doctor_id, p.name AS patient_name
        FROM conversation_messages m
        JOIN conversations c ON c.id = m.conversation_id
        JOIN patients p ON p.id = c.patient_id
        WHERE m.superseded_by_message_id IS NULL
          AND c.archived_at IS NULL
        ORDER BY m.conversation_id, m.created_at ASC
        """,
        conn,
    )
    cid = pd.read_sql_query(
        "SELECT DISTINCT cid_label FROM patients WHERE cid_label IS NOT NULL AND cid_label != ''",
        conn,
    )

    funnel = ExportFunnel(scanned=int(msgs["conversation_id"].nunique()))
    targets = []
    for conv_id, grp in msgs.groupby("conversation_id"):
        target, reason = evaluate_conversation(conv_id, grp)
        if target is None:
            funnel.drop(reason or "unknown")
        else:
            targets.append(target)
            funnel.exported += 1

    final_ids = [t.message_id for t in targets]
    if final_ids:
        placeholders = ",".join("?" * len(final_ids))
        aux = pd.read_sql_query(
            f"""
            SELECT * FROM conversation_message_llm_calls
            WHERE assistant_message_id IN ({placeholders})
            ORDER BY assistant_message_id, sequence ASC
            """,
            conn,
            params=final_ids,
        )
    else:
        aux = pd.DataFrame()
    conn.close()

    rows = build_export_rows(targets, aux, salt=SALT, pseudonymize_fn=pseudonymize_id)

    pcdt_texts = []
    for r in rows:
        if r["call_type"] != "generate":
            continue
        for m in r["llm_input"]:
            pcdt_texts.append(str(m.get("content") or ""))

    fake_names = {t.patient_id: assign_fake_name(t.patient_id, SALT) for t in targets}
    allow = build_clinical_allow_list(
        pcdt_texts=pcdt_texts,
        patient_names=[t.patient_name for t in targets],
        fake_names=fake_names.values(),
        cid_labels=cid["cid_label"].tolist(),
    )
    registry = ReplacementRegistry(SALT)

    # Anonimiza por conversa; descarta conversa inteira se generate falhar validação.
    by_conv: dict[str, list[dict]] = {}
    for r in rows:
        by_conv.setdefault(r["conversation_id"], []).append(r)

    out_rows: list[dict] = []
    for _conv_id, conv_rows in by_conv.items():
        generate_row = next(x for x in conv_rows if x["call_type"] == "generate")
        anon_in, anon_out, _ = anonymize_sft_text(
            generate_row["llm_input"],
            generate_row["llm_output"],
            registry=registry,
            fake_names=fake_names,
            allow_list=allow,
            patient_id=generate_row["_raw_patient_id"],
            patient_name=generate_row["_patient_name"],
        )
        ok, _ = validate_anonymization(
            llm_input=anon_in,
            llm_output=anon_out,
            original_llm_input=generate_row["llm_input"],
            original_llm_output=generate_row["llm_output"],
            patient_name=generate_row["_patient_name"],
            fake_name=fake_names.get(generate_row["_raw_patient_id"]),
        )
        if not ok:
            funnel.exported -= 1
            funnel.drop("pii_validation_failed")
            continue

        out_rows.append(
            {
                "conversation_id": generate_row["conversation_id"],
                "patient_id": generate_row["patient_id"],
                "doctor_id": generate_row["doctor_id"],
                "message_id": generate_row["message_id"],
                "call_type": "generate",
                "sequence": -1,
                "model": None,
                "llm_input": anon_in,
                "llm_output": anon_out,
            }
        )

        for r in conv_rows:
            if r["call_type"] == "generate":
                continue
            aux_in, aux_out, _ = anonymize_sft_text(
                r["llm_input"],
                r["llm_output"],
                registry=registry,
                fake_names=fake_names,
                allow_list=allow,
                patient_id=r["_raw_patient_id"],
                patient_name=r["_patient_name"],
            )
            out_rows.append(
                {
                    "conversation_id": r["conversation_id"],
                    "patient_id": r["patient_id"],
                    "doctor_id": r["doctor_id"],
                    "message_id": r["message_id"],
                    "call_type": r["call_type"],
                    "sequence": r["sequence"],
                    "model": r["model"],
                    "llm_input": aux_in,
                    "llm_output": aux_out,
                }
            )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as fh:
        for row in out_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Wrote {len(out_rows)} lines to {OUTPUT_PATH}")
    print(f"Funnel: scanned={funnel.scanned} exported={funnel.exported} dropped={funnel.dropped}")
    print(f"Registry counts: {registry.counts}")


if __name__ == "__main__":
    main()
