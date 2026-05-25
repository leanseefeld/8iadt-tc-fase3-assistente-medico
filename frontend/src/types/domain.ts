/** DTOs alinhados a API_ASSUMPTIONS.md e referencia-frontend.md */

export type PatientSex = 'M' | 'F';

export type PatientGender =
  | 'mulher_cis'
  | 'homem_cis'
  | 'mulher_trans'
  | 'homem_trans'
  | 'travesti'
  | 'nao_binario'
  | 'outro';

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
  completedAt?: string;
  status: ExamStatus;
  result?: string;
  interpretation?: string;
  source: ExamSource;
  protocolRef?: string;
  attachments?: ExamAttachment[];
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
  gender?: PatientGender | string;
  symptoms: string;
  comorbidities: string[];
  currentMedications: string[];
  vitalSigns: VitalSigns;
  exams: Exam[];
  agentLog: AgentLogEntry[];
}

export type GuardrailStatus = 'safe' | 'warned' | 'blocked' | 'regenerated';

export type MessageFeedbackRating = 'positive' | 'negative';

export interface ChatResponse {
  text: string;
  sources: string[];
  reasoning: string[];
  /** Presente quando o backend devolve o id do thread (LangGraph checkpointer). */
  threadId?: string;
  /** Id persistido da mensagem do assistente neste turno. */
  messageId?: string;
  /** Status do guardrail de segurança clínica. Ausente se não aplicável. */
  guardrailStatus?: GuardrailStatus;
}

export interface MessageFeedbackPatchResponse {
  messageId: string;
  feedbackRating: MessageFeedbackRating | null;
}

export interface ConversationSummary {
  id: string;
  patientId: string;
  createdAt: string;
  updatedAt: string;
  preview?: string | null;
}

export interface ConversationListResponse {
  conversations: ConversationSummary[];
}

export interface ConversationMessageDto {
  id: string;
  author: 'user' | 'assistant';
  content: string;
  sources?: string[] | null;
  reasoningSteps?: string[] | null;
  feedbackRating?: MessageFeedbackRating | null;
  createdAt: string;
}

export interface ConversationMessagesResponse {
  conversationId: string;
  patientId: string;
  messages: ConversationMessageDto[];
}

export interface ConversationArchiveResponse {
  id: string;
  archivedAt: string;
  archivedBy: string;
}

export interface CreatePatientRequestBody {
  /** Omisso no mock → "Paciente sem nome". */
  name?: string;
  /** Omisso ou inválido no mock → 45. */
  age?: number;
  sex?: PatientSex;
  /** Omisso → admissão sem CID (code/label vazios). */
  cid?: Cid;
  /** Omisso no mock → "Não informado". */
  observations?: string;
  gender?: PatientGender | string;
  symptoms?: string;
  comorbidities?: string[];
  /** Texto multilinha do formulário; normalizado para array no mock */
  currentMedications?: string;
}
