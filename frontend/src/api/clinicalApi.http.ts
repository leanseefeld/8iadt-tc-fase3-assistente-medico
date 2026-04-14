/**
 * Transporte HTTP (ver API_ASSUMPTIONS.md).
 * Chat com SSE está implementado; demais rotas ainda não — use híbrido em clinicalApi.ts.
 */
import { API_BASE_URL } from '@/api/client';
import type { Alert } from '@/types/alert';
import type {
  Cid,
  CreatePatientRequestBody,
  DecisionFlowResponse,
  Patient,
  PatientStatus,
  ChatResponse,
} from '@/types/domain';
import type { PatchPatientBody } from '@/api/clinicalApi.memory';
import {
  consumeAssistantChatSse,
  type ChatStreamHandlers,
} from '@/api/sseChat';

export type { PatchPatientBody, ChatStreamHandlers };

function notImplemented(): never {
  throw new Error(
    'clinicalApi.http: transporte HTTP ainda não implementado. Remova VITE_CLINICAL_API_HTTP ou complete src/api/clinicalApi.http.ts.',
  );
}

export async function getCidListMock(): Promise<Cid[]> {
  notImplemented();
}

export async function getPatientsMock(_params?: {
  status?: PatientStatus | string;
  q?: string;
}): Promise<Patient[]> {
  notImplemented();
}

export async function searchPatientsMock(_query: string): Promise<Patient[]> {
  notImplemented();
}

export async function createPatientMock(
  _body: CreatePatientRequestBody,
): Promise<Patient> {
  notImplemented();
}

export async function getPatientByIdMock(_id: string): Promise<Patient | null> {
  notImplemented();
}

export async function patchPatientMock(
  _id: string,
  _patch: PatchPatientBody,
): Promise<Patient | null> {
  notImplemented();
}

export async function getAlertsMock(_params?: {
  patientId?: string;
  severity?: Alert['severity'];
  team?: Alert['team'];
  resolved?: boolean;
}): Promise<Alert[]> {
  notImplemented();
}

export async function patchAlertMock(
  _alertId: string,
  _body: { resolved: boolean },
): Promise<Alert | null> {
  notImplemented();
}

export async function postAssistantChatMock(
  patientId: string,
  message: string,
  handlers?: ChatStreamHandlers,
): Promise<ChatResponse> {
  const url = `${API_BASE_URL}/assistant/chat`;
  const body = JSON.stringify({ patientId, message });
  const useSse = Boolean(
    handlers && (handlers.onToken != null || handlers.onMeta != null),
  );

  if (useSse) {
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      body,
    });
    if (!res.ok) {
      const detail = await parseHttpErrorDetail(res);
      handlers?.onError?.(detail);
      throw new Error(detail);
    }
    return consumeAssistantChatSse(res, handlers);
  }

  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body,
  });
  if (!res.ok) {
    throw new Error(await parseHttpErrorDetail(res));
  }
  return (await res.json()) as ChatResponse;
}

async function parseHttpErrorDetail(res: Response): Promise<string> {
  const fallback = `Erro HTTP ${res.status}`;
  const raw = await res.text();
  if (!raw.trim()) {
    return fallback;
  }
  try {
    const j = JSON.parse(raw) as { detail?: unknown };
    if (typeof j.detail === 'string') {
      return j.detail;
    }
  } catch {
    /* corpo não é JSON */
  }
  return raw.slice(0, 280);
}

export async function postAssistantDecisionFlowMock(
  _patientId: string,
): Promise<DecisionFlowResponse> {
  notImplemented();
}

export async function getUnresolvedAlertCountMock(): Promise<number> {
  notImplemented();
}

export async function getAlertsForPatientMock(
  _patientId: string,
): Promise<Alert[]> {
  notImplemented();
}

export async function addAlertMock(
  _input: Omit<Alert, 'id' | 'createdAt'>,
): Promise<Alert> {
  notImplemented();
}
