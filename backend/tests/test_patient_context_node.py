"""Testes das funções de formatação do nó load_patient_context."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from assistente_medico_api.graph.nodes.patient_context import (
    format_exam_sections,
    format_gender_label,
    format_patient_context,
    format_relative_time,
    format_sex_label,
    format_symptoms_block,
    resolve_comorbidity_labels,
)
from assistente_medico_api.models.exam import Exam
from assistente_medico_api.models.patient import Patient


def test_format_sex_label():
    assert format_sex_label("M") == "Masculino"
    assert format_sex_label("F") == "Feminino"
    assert format_sex_label("X") == "X"


def test_format_gender_label_known_and_unknown():
    assert format_gender_label("mulher_trans") == "Mulher transgênero"
    assert format_gender_label("codigo_custom") == "codigo_custom"
    assert format_gender_label(None) is None


def test_resolve_comorbidity_labels():
    labels = resolve_comorbidity_labels(["HAS", "codigo_x"])
    assert labels == ["Hipertensão Arterial Sistêmica", "codigo_x"]


def test_format_symptoms_block_multiline_and_empty():
    assert format_symptoms_block("febre\ntosse\n") == "  - febre\n  - tosse"
    assert format_symptoms_block("   ") == ""


def test_format_relative_time_days_hours_minutes():
    ref = datetime(2026, 5, 24, 12, 0, tzinfo=UTC)
    assert format_relative_time(ref - timedelta(days=3), ref) == "há 3 dias"
    assert format_relative_time(ref - timedelta(hours=2), ref) == "há 2 horas"
    assert format_relative_time(ref - timedelta(minutes=5), ref) == "há 5 minutos"
    assert format_relative_time(ref - timedelta(seconds=30), ref) == "há menos de 1 minuto"


def test_format_exam_sections_filters_and_orders():
    ref = datetime(2026, 5, 24, 12, 0, tzinfo=UTC)
    cutoff = ref - timedelta(days=183)
    old_exam = Exam(
        id="ex-old",
        patient_id="pt-1",
        name="Exame antigo",
        requested_at=ref - timedelta(days=200),
        status="completed",
        result="1 mg/dL",
        completed_at=ref - timedelta(days=200),
    )
    pending_recent = Exam(
        id="ex-p1",
        patient_id="pt-1",
        name="Creatinina",
        requested_at=ref - timedelta(days=5),
        status="pending",
    )
    pending_older = Exam(
        id="ex-p2",
        patient_id="pt-1",
        name="TSH",
        requested_at=ref - timedelta(days=10),
        status="pending",
    )
    completed = Exam(
        id="ex-c1",
        patient_id="pt-1",
        name="HbA1c",
        requested_at=ref - timedelta(days=2),
        status="completed",
        result="8,2%",
        completed_at=ref - timedelta(hours=3),
    )
    completed_legacy = Exam(
        id="ex-c2",
        patient_id="pt-1",
        name="Glicemia",
        requested_at=ref - timedelta(days=1),
        status="critical",
        result="300 mg/dL",
        completed_at=None,
    )

    pending_text, completed_text = format_exam_sections(
        [old_exam, pending_recent, pending_older, completed, completed_legacy],
        cutoff=cutoff,
        reference=ref,
    )

    assert "Exame antigo" not in pending_text + completed_text
    assert pending_text.index("TSH") < pending_text.index("Creatinina")
    assert "pendente" in pending_text
    assert "8,2%" in completed_text
    assert "data não registrada" in completed_text


def test_format_patient_context_with_and_without_optional_fields():
    ref = datetime(2026, 5, 24, 12, 0, tzinfo=UTC)
    patient = Patient(
        id="pt-1",
        name="Maria Oliveira",
        age=38,
        sex="F",
        gender="mulher_trans",
        status="admitted",
        admitted_at=ref,
        cid_code="E11",
        cid_label="Diabetes Mellitus Tipo 2",
        observations="Obs",
        symptoms="febre\n tosse seca ",
        comorbidities=["HAS"],
        current_medications=["Metformina"],
    )
    exams = [
        Exam(
            id="ex-1",
            patient_id="pt-1",
            name="Creatinina",
            requested_at=ref - timedelta(days=1),
            status="pending",
        )
    ]

    text = format_patient_context(patient, exams, reference=ref)
    assert "Maria Oliveira" in text
    assert "Mulher transgênero" in text
    assert "febre" in text
    assert "Hipertensão Arterial Sistêmica" in text
    assert "Creatinina" in text

    patient_no_gender = patient.model_copy(update={"gender": None, "symptoms": ""})
    text2 = format_patient_context(patient_no_gender, [], reference=ref)
    assert "Identidade de gênero" not in text2
    assert "Sintomas: Não informado" in text2


def test_format_patient_context_with_completed_exams():
    """Valida que exames concluídos aparecem corretamente no contexto."""
    ref = datetime(2026, 5, 24, 12, 0, tzinfo=UTC)
    patient = Patient(
        id="pt-1",
        name="João Silva",
        age=45,
        sex="M",
        status="admitted",
        admitted_at=ref,
        cid_code="E11",
        cid_label="Diabetes Mellitus Tipo 2",
    )
    
    # Exame pendente e exame concluído
    pending_exam = Exam(
        id="ex-pending",
        patient_id="pt-1",
        name="Creatinina",
        requested_at=ref - timedelta(days=5),
        status="pending",
    )
    
    completed_exam = Exam(
        id="ex-completed",
        patient_id="pt-1",
        name="HbA1c",
        requested_at=ref - timedelta(days=2),
        status="completed",
        result="7.5%",
        completed_at=ref - timedelta(hours=1),
    )
    
    text = format_patient_context(patient, [pending_exam, completed_exam], reference=ref)
    
    # Valida estrutura geral - seções estão separadas
    assert "- Exames concluídos (últimos 6 meses):" in text
    assert "- Exames pendentes (últimos 6 meses):" in text
    
    # Valida conteúdo de cada seção
    lines = text.split("\n")
    pending_idx = next(i for i, l in enumerate(lines) if "pendentes" in l)
    completed_idx = next(i for i, l in enumerate(lines) if "concluídos" in l)
    
    # Exame pendente deve estar a partir de "Exames pendentes" (já que é a última seção)
    pending_section = "\n".join(lines[pending_idx:])
    assert "Creatinina" in pending_section
    assert "pendente" in pending_section
    
    # Exame concluído deve estar entre "Exames concluídos" e "Exames pendentes"
    completed_section = "\n".join(lines[completed_idx:pending_idx])
    assert "HbA1c" in completed_section
    assert "7.5%" in completed_section
    assert "concluído" in completed_section
