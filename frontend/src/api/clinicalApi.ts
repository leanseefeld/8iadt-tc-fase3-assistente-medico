/**
 * API clínica: uma única entrada para o app.
 * Na carga do módulo escolhe implementação em memória (padrão) ou HTTP (futuro).
 *
 * @see API_ASSUMPTIONS.md
 */
import * as memory from '@/api/clinicalApi.memory';
import * as http from '@/api/clinicalApi.http';
import { quickQuestionsForCid } from '@/mocks/internal/chatMocks';

function useHttpTransport(): boolean {
  const v = import.meta.env.VITE_CLINICAL_API_HTTP;
  return v === 'true' || v === '1';
}

const impl = useHttpTransport() ? http : memory;

export type PatchPatientBody = memory.PatchPatientBody;

export const getCidListMock = impl.getCidListMock;
export const getPatientsMock = impl.getPatientsMock;
export const searchPatientsMock = impl.searchPatientsMock;
export const createPatientMock = impl.createPatientMock;
export const getPatientByIdMock = impl.getPatientByIdMock;
export const patchPatientMock = impl.patchPatientMock;
export const getAlertsMock = impl.getAlertsMock;
export const patchAlertMock = impl.patchAlertMock;
export const postAssistantChatMock = impl.postAssistantChatMock;
export const postAssistantDecisionFlowMock = impl.postAssistantDecisionFlowMock;
export const getUnresolvedAlertCountMock = impl.getUnresolvedAlertCountMock;
export const getAlertsForPatientMock = impl.getAlertsForPatientMock;
export const addAlertMock = impl.addAlertMock;

/** Lista de perguntas rápidas: função pura, igual em ambos os transportes. */
export { quickQuestionsForCid };
