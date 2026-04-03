/**
 * Mapas de protocolo — consumidos apenas pela camada mock.
 * suggestedActions alimenta Patient.suggestedItems na API.
 */

import type { SuggestedActionType } from '@/types/domain';

export interface ProtocolSuggestedTemplate {
  type: SuggestedActionType;
  description: string;
}

export interface ProtocolResult {
  protocolRef: string;
  exams: string[];
  suggestedActions: ProtocolSuggestedTemplate[];
  drugInteractionAlert?: boolean;
}

export const PROTOCOL_MAP: Record<string, ProtocolResult> = {
  'L40.5': {
    protocolRef: 'PCDT Artrite Psoriásica — CONITEC 2023',
    exams: [
      'Hemograma completo',
      'Contagem de plaquetas',
      'Creatinina sérica',
      'AST/TGO',
      'ALT/TGP',
    ],
    suggestedActions: [
      { type: 'exam', description: 'Solicitar Hemograma completo' },
      { type: 'exam', description: 'Solicitar Contagem de plaquetas' },
      { type: 'exam', description: 'Solicitar Creatinina sérica' },
      { type: 'exam', description: 'Solicitar AST/TGO' },
      { type: 'exam', description: 'Solicitar ALT/TGP' },
      { type: 'observation', description: 'Avaliar acometimento cutâneo (PASI)' },
      { type: 'review', description: 'Reavaliação em 24h' },
    ],
  },
  'A41.9': {
    protocolRef: 'Protocolo de Sepse — MS 2019',
    exams: [
      'Hemoculturas (2 amostras)',
      'Lactato sérico',
      'Hemograma completo',
      'PCR e Procalcitonina',
      'Gasometria arterial',
      'Creatinina e Ureia',
    ],
    suggestedActions: [
      {
        type: 'prescription',
        description:
          'Antibioticoterapia empírica em até 1h (ver protocolo)',
      },
      {
        type: 'exam',
        description: 'Coletar hemoculturas antes dos antibióticos',
      },
      {
        type: 'observation',
        description: 'Monitorar sinais de disfunção orgânica',
      },
      {
        type: 'review',
        description: 'Reavaliação em 6h — bundle de sepse',
      },
    ],
  },
  'T81.4': {
    protocolRef: 'Protocolo Pós-Cirúrgico — Controle de Infecção',
    exams: [
      'Hemograma completo',
      'PCR',
      'Cultura de sítio cirúrgico',
      'Glicemia',
    ],
    suggestedActions: [
      {
        type: 'prescription',
        description:
          'Verificar interação: antibiótico + anticoagulante em uso',
      },
      {
        type: 'exam',
        description: 'Solicitar cultura de sítio cirúrgico',
      },
      {
        type: 'observation',
        description: 'Inspecionar ferida operatória',
      },
    ],
    drugInteractionAlert: true,
  },
  'M05.3': {
    protocolRef: 'Diretriz Artrite Reumatoide — CFM/MS (referência mock)',
    exams: [
      'Hemograma completo',
      'PCR (ves)',
      'Fator reumatoide e anti-CCP',
      'Função hepática (TGO/TGP)',
      'Creatinina',
    ],
    suggestedActions: [
      { type: 'exam', description: 'Solicitar PCR e autoanticorpos' },
      { type: 'exam', description: 'Avaliar marcadores de atividade de doença' },
      {
        type: 'prescription',
        description: 'Avaliar dmard de acordo com protocolo institucional',
      },
      { type: 'review', description: 'Reavaliação ambulatorial em 4–8 semanas' },
    ],
  },
};

const DEFAULT_PROTOCOL: ProtocolResult = {
  protocolRef: 'Protocolo institucional genérico (mock)',
  exams: ['Hemograma completo', 'Creatinina sérica'],
  suggestedActions: [
    { type: 'exam', description: 'Solicitar exames basais conforme protocolo' },
    { type: 'review', description: 'Reavaliação clínica em 24–48h' },
  ],
};

export function getProtocolForCid(code: string): ProtocolResult {
  return PROTOCOL_MAP[code] ?? DEFAULT_PROTOCOL;
}
