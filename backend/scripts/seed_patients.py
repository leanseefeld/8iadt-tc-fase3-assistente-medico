"""Idempotent seed for initial discharged patients."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import select

from assistente_medico_api.config import Settings
from assistente_medico_api.models.patient import Patient
from assistente_medico_api.services.patient_service import append_vitals, apply_protocol

SEED_PATIENTS = [
    {
        "id": "mock-disch-01",
        "name": "Maria Oliveira",
        "age": 62,
        "sex": "F",
        "status": "discharged",
        "admitted_at_days_ago": 14,
        "cid_code": "L40.5",
        "cid_label": "Artrite Psoriásica",
        "observations": "Dor em articulações e rigidez matinal",
        "comorbidities": ["HAS"],
        "current_medications": ["Losartana 50mg"],
    },
    {
        "id": "mock-disch-02",
        "name": "Carlos Mendes",
        "age": 41,
        "sex": "M",
        "status": "discharged",
        "admitted_at_days_ago": 30,
        "cid_code": "T81.4",
        "cid_label": "Infecção pós-procedimento cirúrgico",
        "observations": "Febre e dor no sítio cirúrgico",
        "comorbidities": ["DM2"],
        "current_medications": ["Warfarina 5mg", "Ciprofloxacino 500mg"],
    },
    {
        "id": "mock-disch-03",
        "name": "Ana Costa",
        "age": 54,
        "sex": "F",
        "status": "discharged",
        "admitted_at_days_ago": 7,
        "cid_code": "A41.9",
        "cid_label": "Sepse não especificada",
        "observations": "Hipotensão e taquicardia",
        "comorbidities": ["IRC"],
        "current_medications": [],
    },
    {
        "id": "mock-disch-04",
        "name": "Pedro Alves",
        "age": 58,
        "sex": "M",
        "status": "discharged",
        "admitted_at_days_ago": 45,
        "cid_code": "E11.9",
        "cid_label": "Diabetes Mellitus tipo 2 sem complicações",
        "observations": "Hipoglicemia leve em jejum",
        "comorbidities": ["HAS", "Obesidade"],
        "current_medications": ["Metformina"],
    },
    {
        "id": "mock-disch-05",
        "name": "Roberto Farias",
        "age": 72,
        "sex": "M",
        "status": "discharged",
        "admitted_at_days_ago": 90,
        "cid_code": "I50.0",
        "cid_label": "Insuficiência Cardíaca Congestiva",
        "observations": "Dispneia aos esforços",
        "comorbidities": ["HAS", "DM2"],
        "current_medications": ["Enalapril", "Furosemida"],
    },
]


async def main() -> None:
    settings = Settings()
    engine = create_async_engine(settings.database_url, echo=False)
    SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with SessionLocal() as session:
        existing = await session.execute(select(Patient.id).limit(1))
        if existing.first() is not None:
            print("Seed ignorado: tabela patients já contém dados.")
            return

        now = datetime.now(UTC)
        for row in SEED_PATIENTS:
            patient = Patient(
                id=row["id"],
                name=row["name"],
                age=row["age"],
                sex=row["sex"],
                status=row["status"],
                admitted_at=now - timedelta(days=row["admitted_at_days_ago"]),
                cid_code=row["cid_code"],
                cid_label=row["cid_label"],
                observations=row["observations"],
                comorbidities=row["comorbidities"],
                current_medications=row["current_medications"],
            )
            session.add(patient)
            await session.flush()
            await append_vitals(session, patient=patient)
            await apply_protocol(session, patient, "admission")

        await session.commit()
        print(f"Seed concluído: {len(SEED_PATIENTS)} pacientes inseridos.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
