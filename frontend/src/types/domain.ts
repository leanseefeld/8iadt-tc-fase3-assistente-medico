/** DTOs alinhados a API_ASSUMPTIONS.md e referencia-frontend.md */

export type PatientSex = 'M' | 'F';

export type PatientStatus = 'admitted' | 'discharged';

export interface Cid {
  code: string;
  label: string;
}

export interface MedicationOption {
  code: string;
  label: string;
  activeIngredient: string;
  sourceTags: string[];
}

export interface VitalSigns {
  bloodPressure: string;
  temperature: number;
  oxygenSaturation: number;
  heartRate: number;
  updatedAt: string;
}

export type ExamStatus = 'pending' | 'completed' | 'critical';

export type ExamSource = 'protocol' | 'manual';

export interface ExamAttachment {
  name: string;
  mime: string;
  size: number;
  path: string;
}

export interface Exam {
  id: string;
  name: string;
  requestedAt: string;
  status: ExamStatus;
  result?: string;
  interpretation?: string;
  source: ExamSource;
  protocolRef?: string;
  attachments?: ExamAttachment[];
}

export type SuggestedActionType =
  | 'exam'
  | 'prescription'
  | 'observation'
  | 'review';

export type SuggestedActionStatus =
  | 'suggested'
  | 'accepted'
  | 'modified'
  | 'rejected';

export interface SuggestedActionItem {
  id: string;
  type: SuggestedActionType;
  description: string;
  status: SuggestedActionStatus;
  protocolRef?: string;
}

export type AgentLogStatus = 'done' | 'running' | 'alert' | 'error';

export interface AgentLogEntry {
  step: string;
  status: AgentLogStatus;
  detail: string;
  timestamp: string;
}

export interface Patient {
  id: string;
  name: string;
  age: number;
  sex: PatientSex;
  status: PatientStatus;
  admittedAt: string;
  cid: Cid;
  observations: string;
  comorbidities: string[];
  currentMedications: string[];
  vitalSigns: VitalSigns;
  exams: Exam[];
  suggestedItems: SuggestedActionItem[];
  agentLog: AgentLogEntry[];
}

export interface ChatResponse {
  text: string;
  sources: string[];
  reasoning: string[];
}

export interface DecisionFlowResponse {
  lines: string[];
  meta: {
    sepsisCritical: boolean;
    pharmacyInteraction: boolean;
  };
}

export interface CreatePatientRequestBody {
  /** Omisso no mock → "Paciente sem nome". */
  name?: string;
  /** Omisso ou inválido no mock → 45. */
  age?: number;
  sex?: PatientSex;
  /** Omisso no mock → "S/N". */
  cid: Cid;
  /** Omisso no mock → "Não informado". */
  observations?: string;
  comorbidities?: string[];
  /** Texto multilinha do formulário; normalizado para array no mock */
  currentMedications?: string;
}
