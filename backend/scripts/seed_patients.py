"""Idempotent seed for initial demo patients."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import select

from assistente_medico_api.config import Settings, resolve_database_url
from assistente_medico_api.models.exam import Exam
from assistente_medico_api.models.patient import Patient
from assistente_medico_api.services.patient_service import append_vitals, apply_protocol

# Resultados simulados por CID para o primeiro exame de protocolo de cada paciente.
_SEED_EXAM_RESULTS: dict[str, tuple[str, int]] = {
    "J45.9": ("Espirometria: VEF1 62% do previsto", 2),
    "L40.5": ("PCR: 18 mg/L", 5),
    "T81.4": ("Hemocultura: positiva para E. coli", 1),
    "A41.9": ("Lactato: 4,2 mmol/L", 0),
    "E11.9": ("Glicemia em jejum: 145 mg/dL", 3),
    "I50.0": ("BNP: 890 pg/mL", 7),
}

SEED_PATIENTS = [
    {
        "id": "mock-adm-01",
        "name": "Julia Santos",
        "age": 37,
        "sex": "F",
        "gender": None,
        "status": "admitted",
        "admitted_at_days_ago": 1,
        "cid_code": "J45.9",
        "cid_label": "Asma não especificada",
        "observations": "Dispneia e sibilância em observação",
        "symptoms": "Dispneia\nSibilância",
        "comorbidities": ["Asma"],
        "current_medications": ["Salbutamol"],
    },
    {
        "id": "mock-disch-01",
        "name": "Maria Oliveira",
        "age": 62,
        "sex": "F",
        "gender": "mulher_cis",
        "status": "discharged",
        "admitted_at_days_ago": 14,
        "cid_code": "L40.5",
        "cid_label": "Artrite Psoriásica",
        "observations": "Dor em articulações e rigidez matinal",
        "symptoms": "Dor nas articulações\nRigidez matinal",
        "comorbidities": ["HAS"],
        "current_medications": ["Losartana 50mg"],
    },
    {
        "id": "mock-disch-02",
        "name": "Carlos Mendes",
        "age": 41,
        "sex": "M",
        "gender": "homem_cis",
        "status": "discharged",
        "admitted_at_days_ago": 30,
        "cid_code": "T81.4",
        "cid_label": "Infecção pós-procedimento cirúrgico",
        "observations": "Febre e dor no sítio cirúrgico",
        "symptoms": "Febre\nDor no sítio cirúrgico",
        "comorbidities": ["DM2"],
        "current_medications": ["Warfarina 5mg", "Ciprofloxacino 500mg"],
    },
    {
        "id": "mock-disch-03",
        "name": "Ana Costa",
        "age": 54,
        "sex": "F",
        "gender": "mulher_trans",
        "status": "discharged",
        "admitted_at_days_ago": 7,
        "cid_code": "A41.9",
        "cid_label": "Sepse não especificada",
        "observations": "Hipotensão e taquicardia",
        "symptoms": "Hipotensão\nTaquicardia",
        "comorbidities": ["IRC"],
        "current_medications": [],
    },
    {
        "id": "mock-disch-04",
        "name": "Pedro Alves",
        "age": 58,
        "sex": "M",
        "gender": None,
        "status": "discharged",
        "admitted_at_days_ago": 45,
        "cid_code": "E11.9",
        "cid_label": "Diabetes Mellitus tipo 2 sem complicações",
        "observations": "Hipoglicemia leve em jejum",
        "symptoms": "Hipoglicemia leve em jejum",
        "comorbidities": ["HAS", "Obesidade"],
        "current_medications": ["Metformina"],
    },
    {
        "id": "mock-disch-05",
        "name": "Roberto Farias",
        "age": 72,
        "sex": "M",
        "gender": None,
        "status": "discharged",
        "admitted_at_days_ago": 90,
        "cid_code": "I50.0",
        "cid_label": "Insuficiência Cardíaca Congestiva",
        "observations": "Dispneia aos esforços",
        "symptoms": "Dispneia aos esforços\nEdema em membros inferiores",
        "comorbidities": ["HAS", "DM2"],
        "current_medications": ["Enalapril", "Furosemida"],
    },
]


async def _complete_first_protocol_exam(
    session,
    *,
    patient: Patient,
    now: datetime,
) -> None:
    """Marca o primeiro exame de protocolo como concluído com resultado simulado."""
    result = await session.execute(select(Exam).where(Exam.patient_id == patient.id))
    exams = list(result.scalars())
    if not exams:
        return

    result_text, days_ago = _SEED_EXAM_RESULTS.get(
        patient.cid_code,
        ("Resultado dentro do fluxo de demonstração", 2),
    )
    first = exams[0]
    first.status = "completed"
    first.result = result_text
    first.completed_at = now - timedelta(days=days_ago)


async def main() -> None:
    settings = Settings()
    engine = create_async_engine(resolve_database_url(settings), echo=False)
    SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with SessionLocal() as session:
        existing = await session.execute(select(Patient.id).where(Patient.id.in_([p["id"] for p in SEED_PATIENTS])))
        existing_ids = set(existing.scalars().all())
        missing_patients = [p for p in SEED_PATIENTS if p["id"] not in existing_ids]
        if not missing_patients:
            print("Seed ignorado: todos os pacientes iniciais já existem.")
            return

        now = datetime.now(UTC)
        for row in missing_patients:
            patient = Patient(
                id=row["id"],
                name=row["name"],
                age=row["age"],
                sex=row["sex"],
                gender=row.get("gender"),
                status=row["status"],
                admitted_at=now - timedelta(days=row["admitted_at_days_ago"]),
                cid_code=row["cid_code"],
                cid_label=row["cid_label"],
                observations=row["observations"],
                symptoms=row.get("symptoms", ""),
                comorbidities=row["comorbidities"],
                current_medications=row["current_medications"],
            )
            session.add(patient)
            await session.flush()
            await append_vitals(session, patient=patient)
            await apply_protocol(session, patient, "admission")
            await _complete_first_protocol_exam(session, patient=patient, now=now)

        await session.commit()
        print(f"Seed concluído: {len(missing_patients)} pacientes inseridos.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
