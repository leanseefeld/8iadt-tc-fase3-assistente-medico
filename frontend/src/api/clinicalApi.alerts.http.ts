import { API_BASE_URL } from '@/api/client';
import type { Alert } from '@/types/alert';

export async function getAlertsHttp(params?: {
  patientId?: string;
  resolved?: boolean;
  severity?: string;
  team?: string;
}): Promise<Alert[]> {
  const url = new URL(`${API_BASE_URL}/alerts`);
  if (params?.patientId) {
    url.searchParams.set('patient_id', params.patientId);
  }
  if (params?.resolved !== undefined) {
    url.searchParams.set('resolved', String(params.resolved));
  }
  if (params?.severity) {
    url.searchParams.set('severity', params.severity);
  }
  if (params?.team) {
    url.searchParams.set('team', params.team);
  }

  const res = await fetch(url, {
    headers: { Accept: 'application/json' },
  });
  if (!res.ok) {
    throw new Error(`Falha ao listar alertas: HTTP ${res.status}`);
  }
  return ((await res.json()) as { alerts: Alert[] }).alerts;
}

export async function getAlertByIdHttp(id: string): Promise<Alert | null> {
  const res = await fetch(`${API_BASE_URL}/alerts/${id}`, {
    headers: { Accept: 'application/json' },
  });
  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`Falha ao buscar alerta: HTTP ${res.status}`);
  }
  return ((await res.json()) as { alert: Alert }).alert;
}

export async function patchAlertHttp(
  id: string,
  patch: { resolved?: boolean },
): Promise<Alert | null> {
  const res = await fetch(`${API_BASE_URL}/alerts/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(patch),
  });
  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`Falha ao atualizar alerta: HTTP ${res.status}`);
  }
  return ((await res.json()) as { alert: Alert }).alert;
}

export async function createAlertHttp(
  input: Omit<Alert, 'id' | 'createdAt'>,
): Promise<Alert> {
  const res = await fetch(`${API_BASE_URL}/alerts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({
      patientId: input.patientId,
      severity: input.severity,
      category: input.category,
      message: input.message,
      team: input.team,
    }),
  });
  if (!res.ok) {
    throw new Error(`Falha ao criar alerta: HTTP ${res.status}`);
  }
  return ((await res.json()) as { alert: Alert }).alert;
}

export async function getUnresolvedAlertCountHttp(): Promise<number> {
  try {
    const alerts = await getAlertsHttp({ resolved: false });
    return alerts.length;
  } catch {
    return 0;
  }
}
