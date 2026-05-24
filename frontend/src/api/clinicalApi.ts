/**
 * API clinica: uma unica entrada para o app.
 * Todas as chamadas usam o backend via HTTP.
 *
 * @see API_ASSUMPTIONS.md
 */
import * as http from '@/api/clinicalApi.http';
import * as comorbidities from '@/api/clinicalApi.comorbidities';
import * as cidsHttp from '@/api/clinicalApi.cids.http';
import * as medicationsHttp from '@/api/clinicalApi.medications.http';
import * as patientsHttp from '@/api/clinicalApi.patients.http';
import * as examsHttp from '@/api/clinicalApi.exams.http';
import * as suggestedItemsHttp from '@/api/clinicalApi.suggestedItems.http';
import * as alertsHttp from '@/api/clinicalApi.alerts.http';
import * as prescriptionsHttp from '@/api/clinicalApi.prescriptions.http';
import type {
  PatchPatientBody,
  ReAdmitOverrides,
} from '@/api/clinicalApi.types';
import type { PrescriptionCreateBody } from '@/types/prescription';
import { quickQuestionsForCid } from '@/mocks/internal/chatMocks';
import type { AssistantChatRequestOptions } from '@/api/clinicalApi.http';

export type { AssistantChatRequestOptions, AssistantMessageHistoryItem } from '@/api/clinicalApi.http';
export type { ChatStreamHandlers } from '@/api/sseChat';
export type { PatchPatientBody, ReAdmitOverrides } from '@/api/clinicalApi.types';
export type { Prescription, PrescriptionCreateBody } from '@/types/prescription';

function parseMedicationLines(text?: string): string[] {
  if (!text?.trim()) {
    return [];
  }
  return text
    .split(/\n/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export async function getCidListMock() {
  return cidsHttp.getCidListHttp();
}

export async function getMedicationCatalogMock() {
  return medicationsHttp.getMedicationCatalogHttp();
}

export async function getPatientsMock(params?: { status?: string; q?: string }) {
  return patientsHttp.getPatientsHttp(params);
}

export async function searchPatientsMock(query: string) {
  return patientsHttp.searchPatientsHttp(query);
}

export async function createPatientMock(
  body: Parameters<typeof patientsHttp.createPatientHttp>[0],
) {
  return patientsHttp.createPatientHttp(body);
}

export async function reAdmitPatientMock(
  patientId: string,
  overrides?: ReAdmitOverrides,
) {
  const patient = await patientsHttp.reAdmitPatientHttp(patientId);
  if (!patient || !overrides) {
    return patient;
  }

  const followUpPatch: PatchPatientBody = {};
  if (overrides.observations?.trim()) {
    followUpPatch.observations = overrides.observations.trim();
  }
  if (overrides.comorbidities != null) {
    followUpPatch.comorbidities = [...overrides.comorbidities];
  }
  if (overrides.currentMedications !== undefined) {
    followUpPatch.currentMedications = parseMedicationLines(
      overrides.currentMedications,
    );
  }

  if (Object.keys(followUpPatch).length === 0) {
    return patient;
  }
  return patientsHttp.patchPatientHttp(patientId, followUpPatch);
}

export async function getPatientByIdMock(id: string) {
  return patientsHttp.getPatientByIdHttp(id);
}

export async function getPatientVitalsHistoryMock(id: string) {
  return patientsHttp.getPatientVitalsHistoryHttp(id);
}

export type PatchPatientOptions = {
  vitalsAuditDemo?: boolean;
  examResultAuditDemo?: boolean;
};

export async function patchPatientMock(
  id: string,
  patch: PatchPatientBody,
  options?: PatchPatientOptions,
) {
  const { exams, suggestedItems, vitalSigns, ...corePatch } = patch;
  let patient = await patientsHttp.patchPatientHttp(id, corePatch);
  if (!patient) {
    return null;
  }

  if (vitalSigns) {
    const afterVitals = await patientsHttp.patchVitalsHttp(id, vitalSigns, {
      auditContextDemo: options?.vitalsAuditDemo,
    });
    if (!afterVitals) {
      return null;
    }
    patient = afterVitals;
  }

  if (exams?.length) {
    for (const examPatch of exams) {
      if (!examPatch.id) {
        continue;
      }
      await examsHttp.patchExamHttp(
        id,
        examPatch.id,
        {
          status: examPatch.status,
          result: examPatch.result,
          interpretation: examPatch.interpretation,
        },
        options?.examResultAuditDemo ? { auditContextDemo: true } : undefined,
      );
    }
  }

  if (suggestedItems?.length) {
    for (const itemPatch of suggestedItems) {
      if (!itemPatch.id) {
        continue;
      }
      await suggestedItemsHttp.patchSuggestedItemHttp(id, itemPatch.id, {
        status: itemPatch.status,
        description: itemPatch.description,
      });
    }
  }

  return patientsHttp.getPatientByIdHttp(id);
}

export async function getAlertsMock() {
  return alertsHttp.getAlertsHttp();
}

export async function patchAlertMock(id: string, patch: { resolved: boolean }) {
  return alertsHttp.patchAlertHttp(id, patch);
}

export async function getUnresolvedAlertCountMock() {
  return alertsHttp.getUnresolvedAlertCountHttp();
}

export async function getAlertsForPatientMock(patientId: string) {
  return alertsHttp.getAlertsHttp({ patientId });
}

export async function getPrescriptionsMock(
  patientId: string,
  includeArchived = false,
) {
  return prescriptionsHttp.getPrescriptionsHttp(patientId, includeArchived);
}

export async function createPrescriptionMock(
  patientId: string,
  body: PrescriptionCreateBody,
) {
  return prescriptionsHttp.createPrescriptionHttp(patientId, body);
}

export async function getPrescriptionByIdMock(id: string) {
  return prescriptionsHttp.getPrescriptionByIdHttp(id);
}

export async function archivePrescriptionMock(
  id: string,
  reason: string,
  archivedBy: string,
) {
  return prescriptionsHttp.archivePrescriptionHttp(id, reason, archivedBy);
}

export async function addAlertMock(
  alert: Parameters<typeof alertsHttp.createAlertHttp>[0],
) {
  return alertsHttp.createAlertHttp(alert);
}

export const postAssistantDecisionFlowMock = http.postAssistantDecisionFlowMock;

export async function postAssistantChatMock(
  patientId: string,
  message: string,
  options?: AssistantChatRequestOptions,
) {
  return http.postAssistantChatMock(patientId, message, options);
}

export const patchAssistantMessageFeedback = http.patchAssistantMessageFeedback;

/** Lista de perguntas rápidas: função pura, igual em ambos os transportes. */
export { quickQuestionsForCid };

/** Comorbidities endpoint: reference data for patient check-in */
export const getComorbidities = comorbidities.getComorbidities;
export const clearComorbidititiesCache = comorbidities.clearComorbidititiesCache;
export type { ComorbidityOption, ComorbidititiesResponse } from '@/api/clinicalApi.comorbidities';
