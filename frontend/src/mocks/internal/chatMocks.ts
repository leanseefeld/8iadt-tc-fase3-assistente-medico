/** Perguntas rápidas e respostas mock — só para a camada mock. */

import type { ChatResponse } from '@/types/domain';

export const QUICK_QUESTIONS: Record<string, string[]> = {
  'L40.5': [
    'Quais exames estão pendentes?',
    'Há contraindicação ao metotrexato neste paciente?',
    'Qual o protocolo recomendado para artrite psoriásica?',
    'Resumir o caso clínico atual',
  ],
  'A41.9': [
    'Quais exames estão pendentes?',
    'Bundle de sepse está completo?',
    'Qual antibiótico empírico recomendar?',
    'Paciente apresenta critérios de UTI?',
  ],
  default: [
    'Quais exames estão pendentes?',
    'Resumir o caso clínico atual',
    'Há alertas ativos?',
    'Qual a ação sugerida?',
  ],
};

export function quickQuestionsForCid(code: string): string[] {
  if (QUICK_QUESTIONS[code]) {
    return QUICK_QUESTIONS[code]!;
  }
  if (code.startsWith('L40')) {
    return QUICK_QUESTIONS['L40.5']!;
  }
  if (code.startsWith('A41')) {
    return QUICK_QUESTIONS['A41.9']!;
  }
  return QUICK_QUESTIONS.default!;
}

/** Chave = texto exato da pergunta (demo). */
export const MOCK_RESPONSES: Record<string, ChatResponse> = {
  'Quais exames estão pendentes?': {
    text: 'Com base no protocolo para L40.5 (Artrite Psoriásica), os seguintes exames estão pendentes:\n\n• Hemograma completo\n• Contagem de plaquetas\n• Creatinina sérica\n• AST/TGO\n• ALT/TGP\n\nEsses exames são necessários para avaliação basal antes do início da terapia modificadora.',
    sources: ['PCDT Artrite Psoriásica — CONITEC 2023'],
    reasoning: [
      "Buscou: 'artrite psoriásica avaliação laboratorial'",
      'Encontrou: PCDT seção 4.2 — Critérios de Inclusão e Avaliação Basal',
      'Extraiu: lista de exames obrigatórios pré-tratamento',
    ],
  },
  'Há contraindicação ao metotrexato neste paciente?': {
    text: 'Em modo demo: verifique função hepática e renal (exames pendentes), gestação/lactação e interações. O PCDT lista contraindicações absolutas e relativas; completar antes de prescrever.',
    sources: ['PCDT Artrite Psoriásica — CONITEC 2023', 'Bula Metotrexato — ANVISA (mock)'],
    reasoning: [
      'Buscou: contraindicações metotrexato artrite psoriásica',
      'Sintetizou: critérios de exclusão habituais',
    ],
  },
  'Qual o protocolo recomendado para artrite psoriásica?': {
    text: 'O protótipo referencia o PCDT Artrite Psoriásica (CONITEC 2023) para investigação basal, critérios de elegibilidade a DMARDs e seguimento.',
    sources: ['PCDT Artrite Psoriásica — CONITEC 2023'],
    reasoning: ['Consultou referência principal vinculada ao CID L40.5'],
  },
  'Resumir o caso clínico atual': {
    text: 'Paciente em acompanhamento com diagnóstico codificado; condutas e exames sugeridos seguem o protocolo vigente. Detalhes adicionais dependem dos dados informados no check-in.',
    sources: ['Prontuário resumido (mock)'],
    reasoning: ['Agregou CID + queixa + comorbidades do cadastro'],
  },
  'Bundle de sepse está completo?': {
    text: 'Em sepse (A41.9), o bundle inclui lactato, hemoculturas, antibiótico precoce, controle de fonte e fluidos conforme protocolo institucional. Verifique no fluxo de decisão e exames pendentes.',
    sources: ['Protocolo de Sepse — MS 2019'],
    reasoning: ['Mapeou checklist do protocolo de sepse'],
  },
  'Qual antibiótico empírico recomendar?': {
    text: 'Em modo demo: a escolha depende de foco, alergias e risco de resistência. Consulte protocolo local e cultivar hemoculturas antes da primeira dose quando possível.',
    sources: ['Protocolo de Sepse — MS 2019'],
    reasoning: ['Resposta educativa sem prescrição específica no protótipo'],
  },
  'Paciente apresenta critérios de UTI?': {
    text: 'Critérios de UTI (ex.: qSOFA, lactato elevado) devem ser avaliados no contexto clínico e laboratorial. Verifique lactato e monitorização contínua.',
    sources: ['Protocolo de Sepse — MS 2019'],
    reasoning: ['Buscou: critérios UTI sepse'],
  },
  'Há alertas ativos?': {
    text: 'Consulte o Painel de Alertas para alertas não resolvidos ligados ao paciente e à equipe.',
    sources: ['Sistema de alertas (mock)'],
    reasoning: ['Encaminha para módulo de alertas'],
  },
  'Qual a ação sugerida?': {
    text: 'As ações sugeridas pelo assistente estão na página Ações Sugeridas, aguardando aceite ou ajuste do médico.',
    sources: ['Motor de sugestão (mock)'],
    reasoning: ['Apontou para suggestedItems do paciente'],
  },
};
