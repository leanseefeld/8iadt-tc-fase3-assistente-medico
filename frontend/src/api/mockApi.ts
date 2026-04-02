import type { ClinicalAlert } from '@/types/alert';
import type { Patient } from '@/types/patient';
import { MOCK_ALERTS, MOCK_PATIENTS } from '@/api/mockData';

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Simula GET /api/patients?q= */
export async function searchPatientsMock(query: string): Promise<Patient[]> {
  await delay(220);
  const q = query.trim().toLowerCase();
  if (!q) {
    return [...MOCK_PATIENTS];
  }
  return MOCK_PATIENTS.filter(
    (p) =>
      p.id.toLowerCase().includes(q) || p.name.toLowerCase().includes(q),
  );
}

/** Simula GET /api/patients/:id */
export async function getPatientByIdMock(id: string): Promise<Patient | null> {
  await delay(180);
  return MOCK_PATIENTS.find((p) => p.id === id) ?? null;
}

/** Simula GET /api/patients/:id/alerts */
export async function getAlertsForPatientMock(
  patientId: string,
): Promise<ClinicalAlert[]> {
  await delay(200);
  return MOCK_ALERTS.filter((a) => a.patientId === patientId);
}
