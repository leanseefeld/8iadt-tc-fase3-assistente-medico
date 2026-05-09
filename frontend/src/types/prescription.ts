export type PrescriberKind = 'doctor' | 'ai_assistant';

export interface PrescriptionItem {
  medicationName: string;
  concentration?: string;
  pharmaceuticalForm?: string;
  quantity?: string;
  posology?: string;
}

export interface Prescription {
  id: string;
  patientId: string;
  patientCpf?: string | null;
  prescriberKind: PrescriberKind;
  prescriberName: string;
  prescriberCrm?: string | null;
  prescriberCrmUf?: string | null;
  institutionName?: string | null;
  institutionCnpjCnes?: string | null;
  institutionAddress?: string | null;
  institutionPhone?: string | null;
  items: PrescriptionItem[];
  notes?: string | null;
  chatThreadId?: string | null;
  decisionFlowRunId?: string | null;
  issuedAt: string;
  archivedAt?: string | null;
  archivedReason?: string | null;
  archivedBy?: string | null;
}

export interface PrescriptionCreateBody {
  patientCpf?: string | null;
  prescriberKind: PrescriberKind;
  prescriberName: string;
  prescriberCrm?: string | null;
  prescriberCrmUf?: string | null;
  institutionName?: string | null;
  institutionCnpjCnes?: string | null;
  institutionAddress?: string | null;
  institutionPhone?: string | null;
  items: PrescriptionItem[];
  notes?: string | null;
  chatThreadId?: string | null;
  decisionFlowRunId?: string | null;
}
