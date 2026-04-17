/**
 * API clínica: uma única entrada para o app.
 * Com `VITE_CLINICAL_API_HTTP=true`, apenas o **chat** usa HTTP/SSE; o restante continua em memória
 * até as rotas CRUD existirem no backend.
 *
 * @see API_ASSUMPTIONS.md
 */
import * as memory from '@/api/clinicalApi.memory';
import * as http from '@/api/clinicalApi.http';
import * as comorbidities from '@/api/clinicalApi.comorbidities';
import { quickQuestionsForCid } from '@/mocks/internal/chatMocks';
import type { ChatStreamHandlers } from '@/api/sseChat';

export type { ChatStreamHandlers };

export function clinicalApiUsesHttp(): boolean {
  const v = import.meta.env.VITE_CLINICAL_API_HTTP;
  return v === 'true' || v === '1';
}

export type PatchPatientBody = memory.PatchPatientBody;

export const getCidListMock = memory.getCidListMock;
export const getPatientsMock = memory.getPatientsMock;
export const searchPatientsMock = memory.searchPatientsMock;
export const createPatientMock = memory.createPatientMock;
export const reAdmitPatientMock = memory.reAdmitPatientMock;
export const getPatientByIdMock = memory.getPatientByIdMock;
export const patchPatientMock = memory.patchPatientMock;
export const getAlertsMock = memory.getAlertsMock;
export const patchAlertMock = memory.patchAlertMock;
export const postAssistantDecisionFlowMock = memory.postAssistantDecisionFlowMock;
export const getUnresolvedAlertCountMock = memory.getUnresolvedAlertCountMock;
export const getAlertsForPatientMock = memory.getAlertsForPatientMock;
export const addAlertMock = memory.addAlertMock;

export async function postAssistantChatMock(
  patientId: string,
  message: string,
  handlers?: ChatStreamHandlers,
) {
  if (clinicalApiUsesHttp()) {
    return http.postAssistantChatMock(patientId, message, handlers);
  }
  return memory.postAssistantChatMock(patientId, message, handlers);
}

/** Lista de perguntas rápidas: função pura, igual em ambos os transportes. */
export { quickQuestionsForCid };

/** Comorbidities endpoint: reference data for patient check-in */
export const getComorbidities = comorbidities.getComorbidities;
export const clearComorbidititiesCache = comorbidities.clearComorbidititiesCache;
export type { ComorbidityOption, ComorbidititiesResponse } from '@/api/clinicalApi.comorbidities';
