import { CID_LIST } from '@/mocks/internal/cidList';
import { MOCK_RESPONSES } from '@/mocks/internal/chatMocks';
import { getProtocolForCid } from '@/mocks/internal/protocolMap';
import type { Alert } from '@/types/alert';
import type {
  Cid,
  CreatePatientRequestBody,
  DecisionFlowResponse,
  Exam,
  Patient,
  PatientStatus,
  SuggestedActionItem,
  ChatResponse,
  VitalSigns,
} from '@/types/domain';
import { mockServerState } from '@/api/mockServerState';

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function newId(prefix: string): string {
  const u =
    typeof crypto !== 'undefined' && crypto.randomUUID
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
  return `${prefix}-${u}`;
}

function defaultVitalSigns(): VitalSigns {
  const now = new Date().toISOString();
  return {
    bloodPressure: '120/80',
    temperature: 36.5,
    oxygenSaturation: 97,
    heartRate: 72,
    updatedAt: now,
  };
}

function parseMedications(text?: string): string[] {
  if (!text?.trim()) {
    return [];
  }
  return text
    .split(/\n/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function buildExamsFromNames(
  names: string[],
  protocolRef: string,
  requestedAt: string,
): Exam[] {
  return names.map((name) => ({
    id: newId('ex'),
    name,
    requestedAt,
    status: 'pending' as const,
    source: 'protocol' as const,
    protocolRef,
  }));
}

function buildSuggestedItemsFromProtocol(
  protocolRef: string,
  templates: { type: SuggestedActionItem['type']; description: string }[],
): SuggestedActionItem[] {
  return templates.map((t) => ({
    id: newId('sa'),
    type: t.type,
    description: t.description,
    status: 'suggested' as const,
    protocolRef,
  }));
}

function applyProtocolToPatientCore(
  patient: Patient,
  cidCode: string,
  protocolRefOverride?: string,
): void {
  const proto = getProtocolForCid(cidCode);
  const protocolRef = protocolRefOverride ?? proto.protocolRef;
  const now = new Date().toISOString();
  patient.exams = buildExamsFromNames(proto.exams, protocolRef, now);
  patient.suggestedItems = buildSuggestedItemsFromProtocol(
    protocolRef,
    proto.suggestedActions,
  );
}

function maybeAlertsOnAdmission(patient: Patient, proto: ReturnType<typeof getProtocolForCid>): void {
  if (patient.cid.code === 'A41.9') {
    mockServerState.alerts.push({
      id: newId('al'),
      patientId: patient.id,
      severity: 'critical',
      category: 'clinical',
      message:
        'Caso crítico — sepse suspeita/confirmada. Alerta imediato para equipe médica.',
      team: 'doctors',
      createdAt: new Date().toISOString(),
      resolved: false,
    });
  }
  if (proto.drugInteractionAlert && patient.cid.code === 'T81.4') {
    mockServerState.alerts.push({
      id: newId('al'),
      patientId: patient.id,
      severity: 'moderate',
      category: 'medication',
      message:
        'Possível interação medicamentosa (antibiótico + anticoagulante). Encaminhado para farmácia.',
      team: 'pharmacy',
      createdAt: new Date().toISOString(),
      resolved: false,
    });
  }
}

function mergeById<T extends { id: string }>(
  current: T[],
  patches: Partial<T>[],
): T[] {
  const map = new Map(current.map((item) => [item.id, { ...item }]));
  for (const patch of patches) {
    if (!patch.id) {
      continue;
    }
    const prev = map.get(patch.id);
    if (prev) {
      map.set(patch.id, { ...prev, ...patch } as T);
    }
  }
  return [...map.values()];
}

function findPatient(id: string): Patient | undefined {
  return mockServerState.patients.find((p) => p.id === id);
}

// ——— API pública (espelha API_ASSUMPTIONS.md) ———

export async function getCidListMock(): Promise<Cid[]> {
  await delay(120);
  return [...CID_LIST];
}

export async function getPatientsMock(params?: {
  status?: PatientStatus | string;
  q?: string;
}): Promise<Patient[]> {
  await delay(160);
  let list = [...mockServerState.patients];
  if (params?.status) {
    list = list.filter((p) => p.status === params.status);
  }
  if (params?.q?.trim()) {
    const q = params.q.trim().toLowerCase();
    list = list.filter(
      (p) =>
        p.id.toLowerCase().includes(q) ||
        p.name.toLowerCase().includes(q),
    );
  }
  return list;
}

export async function searchPatientsMock(query: string): Promise<Patient[]> {
  return getPatientsMock({ q: query });
}

function normalizeAge(age: number | undefined): number {
  if (age === undefined || Number.isNaN(age)) {
    return 45;
  }
  return Math.min(120, Math.max(0, age));
}

export async function createPatientMock(
  body: CreatePatientRequestBody,
): Promise<Patient> {
  await delay(280);
  const proto = getProtocolForCid(body.cid.code);
  const now = new Date().toISOString();
  const name = body.name?.trim() || 'Paciente sem nome';
  const chiefComplaint = body.chiefComplaint?.trim() || 'Não informado';
  const sex = body.sex ?? 'M';
  const age = normalizeAge(body.age);
  const patient: Patient = {
    id: newId('pt'),
    name,
    age,
    sex,
    status: 'admitted',
    admittedAt: now,
    cid: { ...body.cid },
    chiefComplaint,
    comorbidities: body.comorbidities ?? [],
    currentMedications: parseMedications(body.currentMedications),
    vitalSigns: defaultVitalSigns(),
    exams: [],
    suggestedItems: [],
    agentLog: [
      {
        step: 'admission',
        status: 'done',
        detail: `Paciente admitido — CID ${body.cid.code} (${body.cid.label})`,
        timestamp: now,
      },
    ],
  };
  applyProtocolToPatientCore(patient, body.cid.code);
  maybeAlertsOnAdmission(patient, proto);
  mockServerState.patients.push(patient);
  return patient;
}

export type ReAdmitOverrides = {
  chiefComplaint?: string;
  comorbidities?: string[];
  /** Texto multilinha; mesmo formato que createPatientMock. */
  currentMedications?: string;
};

/** Readmite paciente com alta: reaplica protocolo e alertas de admissão (mock). */
export async function reAdmitPatientMock(
  patientId: string,
  overrides?: ReAdmitOverrides,
): Promise<Patient | null> {
  await delay(280);
  const patient = findPatient(patientId);
  if (!patient || patient.status !== 'discharged') {
    return null;
  }
  const proto = getProtocolForCid(patient.cid.code);
  const now = new Date().toISOString();
  if (overrides?.chiefComplaint?.trim()) {
    patient.chiefComplaint = overrides.chiefComplaint.trim();
  }
  if (overrides?.comorbidities != null) {
    patient.comorbidities = [...overrides.comorbidities];
  }
  if (overrides?.currentMedications !== undefined) {
    patient.currentMedications = parseMedications(overrides.currentMedications);
  }
  patient.status = 'admitted';
  patient.admittedAt = now;
  patient.vitalSigns = defaultVitalSigns();
  applyProtocolToPatientCore(patient, patient.cid.code);
  maybeAlertsOnAdmission(patient, proto);
  patient.agentLog.push({
    step: 'readmission',
    status: 'done',
    detail: 'Readmissão — protocolo aplicado (mock).',
    timestamp: now,
  });
  return patient;
}

export async function getPatientByIdMock(id: string): Promise<Patient | null> {
  await delay(140);
  return findPatient(id) ?? null;
}

export type PatchPatientBody = Partial<
  Pick<
    Patient,
    | 'cid'
    | 'status'
    | 'chiefComplaint'
    | 'comorbidities'
    | 'vitalSigns'
  >
> & {
  currentMedications?: string[];
  exams?: Partial<Exam>[];
  suggestedItems?: Partial<SuggestedActionItem>[];
};

export async function patchPatientMock(
  id: string,
  patch: PatchPatientBody,
): Promise<Patient | null> {
  await delay(220);
  const patient = findPatient(id);
  if (!patient) {
    return null;
  }

  if (patch.chiefComplaint != null) {
    patient.chiefComplaint = patch.chiefComplaint;
  }
  if (patch.comorbidities != null) {
    patient.comorbidities = patch.comorbidities;
  }
  if (patch.currentMedications != null) {
    patient.currentMedications = patch.currentMedications;
  }
  if (patch.status != null) {
    patient.status = patch.status;
  }

  if (patch.cid != null) {
    const codeChanged = patch.cid.code !== patient.cid.code;
    patient.cid = { ...patch.cid };
    if (codeChanged) {
      applyProtocolToPatientCore(patient, patient.cid.code);
      patient.agentLog.push({
        step: 'cid-update',
        status: 'done',
        detail: `CID atualizado para ${patient.cid.code} — protocolo re-aplicado (mock).`,
        timestamp: new Date().toISOString(),
      });
    }
  }

  if (patch.vitalSigns != null) {
    patient.vitalSigns = {
      ...patient.vitalSigns,
      ...patch.vitalSigns,
      updatedAt: new Date().toISOString(),
    };
    const spo2 = patient.vitalSigns.oxygenSaturation;
    if (spo2 < 92) {
      mockServerState.alerts.push({
        id: newId('al'),
        patientId: patient.id,
        severity: 'critical',
        category: 'clinical',
        message: `SpO2 ${spo2}% — hipóxia significativa. Avaliar oxigenoterapia e causa.`,
        team: 'doctors',
        createdAt: new Date().toISOString(),
        resolved: false,
      });
    }
  }

  if (patch.exams?.length) {
    const merged = mergeById(patient.exams, patch.exams);
    for (const e of merged) {
      const prev = patient.exams.find((x) => x.id === e.id);
      if (e.status === 'critical' && prev?.status !== 'critical') {
        mockServerState.alerts.push({
          id: newId('al'),
          patientId: patient.id,
          severity: 'critical',
          category: 'exam',
          message: `Resultado crítico: ${e.name}. ${e.result ?? ''}`.trim(),
          team: 'doctors',
          createdAt: new Date().toISOString(),
          resolved: false,
        });
      }
    }
    patient.exams = merged;
  }
  if (patch.suggestedItems?.length) {
    patient.suggestedItems = mergeById(
      patient.suggestedItems,
      patch.suggestedItems,
    );
  }

  return patient;
}

export async function getAlertsMock(params?: {
  patientId?: string;
  severity?: Alert['severity'];
  team?: Alert['team'];
  resolved?: boolean;
}): Promise<Alert[]> {
  await delay(150);
  let list = [...mockServerState.alerts];
  if (params?.patientId != null) {
    list = list.filter((a) => a.patientId === params.patientId);
  }
  if (params?.severity != null) {
    list = list.filter((a) => a.severity === params.severity);
  }
  if (params?.team != null) {
    list = list.filter((a) => a.team === params.team || a.team === 'all');
  }
  if (params?.resolved != null) {
    list = list.filter((a) => a.resolved === params.resolved);
  }
  return list.sort(
    (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
  );
}

export async function patchAlertMock(
  alertId: string,
  body: { resolved: boolean },
): Promise<Alert | null> {
  await delay(160);
  const alert = mockServerState.alerts.find((a) => a.id === alertId);
  if (!alert) {
    return null;
  }
  alert.resolved = body.resolved;
  return alert;
}

export async function postAssistantChatMock(
  patientId: string,
  message: string,
  _handlers?: unknown,
): Promise<ChatResponse> {
  await delay(400);
  const patient = findPatient(patientId);
  const key = message.trim();
  const staticResp = MOCK_RESPONSES[key];
  if (staticResp) {
    return { ...staticResp };
  }
  if (patient && key === 'Quais exames estão pendentes?') {
    const pending = patient.exams.filter((e) => e.status === 'pending');
    const text =
      pending.length === 0
        ? 'Não há exames pendentes para este paciente.'
        : `Exames pendentes:\n\n${pending.map((e) => `• ${e.name}`).join('\n')}`;
    return {
      text,
      sources: patient.suggestedItems[0]?.protocolRef
        ? [patient.suggestedItems[0].protocolRef!]
        : [],
      reasoning: [
        'Consultou lista de exames do prontuário mock',
        'Filtrou status pending',
      ],
    };
  }
  return { text: '', sources: [], reasoning: [] };
}

export async function postAssistantDecisionFlowMock(
  patientId: string,
): Promise<DecisionFlowResponse> {
  await delay(200);
  const patient = findPatient(patientId);
  if (!patient) {
    return {
      lines: ['Erro: paciente não encontrado.'],
      meta: { sepsisCritical: false, pharmacyInteraction: false },
    };
  }
  const proto = getProtocolForCid(patient.cid.code);
  const meta = {
    sepsisCritical: patient.cid.code === 'A41.9',
    pharmacyInteraction:
      patient.cid.code === 'T81.4' && Boolean(proto.drugInteractionAlert),
  };
  const t = new Date();
  const ts = (i: number) =>
    new Date(t.getTime() + i * 1000).toLocaleTimeString('pt-BR', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  const lines: string[] = [
    `✅ [${ts(0)}] Triagem: dados do paciente carregados — ${patient.cid.code}, ${patient.name}, ${patient.age} anos`,
    `🔍 [${ts(1)}] Consultando protocolo: ${proto.protocolRef}`,
    `📋 [${ts(2)}] Exames identificados: ${patient.exams.map((e) => e.name.split(' ')[0]).join(', ')}`,
    `⚙️ [${ts(3)}] Ações sugeridas geradas: ${patient.suggestedItems.length} itens — aguarda aprovação do médico`,
  ];
  if (meta.sepsisCritical) {
    lines.push(
      `🚨 Caso crítico detectado — alerta imediato para equipe médica`,
    );
  }
  if (meta.pharmacyInteraction) {
    lines.push(
      '⚠️ Possível interação medicamentosa detectada — encaminhado para farmácia',
    );
  }
  lines.push(`🔔 [${ts(4)}] Alerta enviado: equipes notificadas conforme regras mock`);
  lines.push(`✅ [${ts(5)}] Fluxo concluído`);
  return { lines, meta };
}

/** Contagem de alertas não resolvidos (badge sidebar). */
export async function getUnresolvedAlertCountMock(): Promise<number> {
  await delay(80);
  return mockServerState.alerts.filter((a) => !a.resolved).length;
}

export async function getAlertsForPatientMock(
  patientId: string,
): Promise<Alert[]> {
  return getAlertsMock({ patientId, resolved: false });
}

/** Cria alerta extra (ex.: “Notificar responsável” na página de exames). */
export async function addAlertMock(
  input: Omit<Alert, 'id' | 'createdAt'>,
): Promise<Alert> {
  await delay(100);
  const alert: Alert = {
    ...input,
    id: newId('al'),
    createdAt: new Date().toISOString(),
  };
  mockServerState.alerts.push(alert);
  return alert;
}
