import { apiFetch, API_BASE_URL } from '@/api/client';
import type { Prescription, PrescriptionCreateBody } from '@/types/prescription';

export async function getPrescriptionsHttp(
  patientId: string,
  includeArchived = false,
): Promise<Prescription[]> {
  const url = new URL(
    `${API_BASE_URL}/patients/${encodeURIComponent(patientId)}/prescriptions`,
  );
  if (includeArchived) {
    url.searchParams.set('includeArchived', 'true');
  }
  const res = await apiFetch(url, { headers: { Accept: 'application/json' } });
  if (!res.ok) {
    throw new Error(`Falha ao listar prescrições: HTTP ${res.status}`);
  }
  const body = (await res.json()) as { prescriptions: Prescription[] };
  return body.prescriptions ?? [];
}

export async function createPrescriptionHttp(
  patientId: string,
  body: PrescriptionCreateBody,
): Promise<Prescription> {
  const res = await apiFetch(
    `${API_BASE_URL}/patients/${encodeURIComponent(patientId)}/prescriptions`,
    {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    },
  );
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(
      `Falha ao criar prescrição: HTTP ${res.status} ${detail.slice(0, 200)}`,
    );
  }
  return ((await res.json()) as { prescription: Prescription }).prescription;
}

export async function getPrescriptionByIdHttp(
  prescriptionId: string,
): Promise<Prescription | null> {
  const res = await apiFetch(
    `${API_BASE_URL}/prescriptions/${encodeURIComponent(prescriptionId)}`,
    { headers: { Accept: 'application/json' } },
  );
  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`Falha ao buscar prescrição: HTTP ${res.status}`);
  }
  return ((await res.json()) as { prescription: Prescription }).prescription;
}

export async function archivePrescriptionHttp(
  prescriptionId: string,
  reason: string,
  archivedBy: string,
): Promise<Prescription> {
  const res = await apiFetch(
    `${API_BASE_URL}/prescriptions/${encodeURIComponent(prescriptionId)}/archive`,
    {
      method: 'PATCH',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ reason, archivedBy }),
    },
  );
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(
      `Falha ao arquivar prescrição: HTTP ${res.status} ${detail.slice(0, 200)}`,
    );
  }
  return ((await res.json()) as { prescription: Prescription }).prescription;
}
