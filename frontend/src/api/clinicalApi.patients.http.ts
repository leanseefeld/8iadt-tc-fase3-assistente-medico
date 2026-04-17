import { API_BASE_URL } from '@/api/client';
import type {
  CreatePatientRequestBody,
  Patient,
  PatientStatus,
  VitalSigns,
} from '@/types/domain';
import type { PatchPatientBody } from '@/api/clinicalApi.types';

function normalizeCreateBody(body: CreatePatientRequestBody): Record<string, unknown> {
  return {
    name: body.name,
    age: body.age,
    sex: body.sex,
    cid: body.cid,
    observations: body.observations,
    comorbidities: body.comorbidities,
    currentMedications: body.currentMedications,
  };
}

export async function getPatientsHttp(params?: {
  status?: PatientStatus | string;
  q?: string;
}): Promise<Patient[]> {
  const url = new URL(`${API_BASE_URL}/patients`);
  if (params?.status) {
    url.searchParams.set('status', params.status);
  }
  if (params?.q) {
    url.searchParams.set('q', params.q);
  }

  const res = await fetch(url, { headers: { Accept: 'application/json' } });
  if (!res.ok) {
    throw new Error(`Falha ao listar pacientes: HTTP ${res.status}`);
  }
  return ((await res.json()) as { patients: Patient[] }).patients;
}

export async function searchPatientsHttp(query: string): Promise<Patient[]> {
  return getPatientsHttp({ q: query });
}

export async function createPatientHttp(body: CreatePatientRequestBody): Promise<Patient> {
  const res = await fetch(`${API_BASE_URL}/patients`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(normalizeCreateBody(body)),
  });
  if (!res.ok) {
    throw new Error(`Falha ao criar paciente: HTTP ${res.status}`);
  }
  return ((await res.json()) as { patient: Patient }).patient;
}

export async function getPatientByIdHttp(id: string): Promise<Patient | null> {
  const res = await fetch(`${API_BASE_URL}/patients/${id}`, {
    headers: { Accept: 'application/json' },
  });
  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`Falha ao buscar paciente: HTTP ${res.status}`);
  }
  return ((await res.json()) as { patient: Patient }).patient;
}

export async function patchPatientHttp(
  id: string,
  patch: PatchPatientBody,
): Promise<Patient | null> {
  const res = await fetch(`${API_BASE_URL}/patients/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(patch),
  });
  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`Falha ao atualizar paciente: HTTP ${res.status}`);
  }
  return ((await res.json()) as { patient: Patient }).patient;
}

export async function patchVitalsHttp(
  id: string,
  patch: Partial<VitalSigns>,
): Promise<Patient | null> {
  const res = await fetch(`${API_BASE_URL}/patients/${id}/vitals`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(patch),
  });
  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`Falha ao atualizar sinais vitais: HTTP ${res.status}`);
  }
  return ((await res.json()) as { patient: Patient }).patient;
}

export async function reAdmitPatientHttp(patientId: string): Promise<Patient | null> {
  const res = await fetch(`${API_BASE_URL}/patients/${patientId}/readmit`, {
    method: 'POST',
    headers: { Accept: 'application/json' },
  });
  if (res.status === 404 || res.status === 409) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`Falha na readmissão: HTTP ${res.status}`);
  }
  return ((await res.json()) as { patient: Patient }).patient;
}
