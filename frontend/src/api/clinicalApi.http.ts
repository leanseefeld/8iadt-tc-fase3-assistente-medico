/**
 * Transporte HTTP futuro (ver API_ASSUMPTIONS.md).
 * Ative com VITE_CLINICAL_API_HTTP=true e implemente as chamadas fetch aqui.
 */
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

export type { PatchPatientBody };

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
  _patientId: string,
  _message: string,
): Promise<ChatResponse> {
  notImplemented();
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
