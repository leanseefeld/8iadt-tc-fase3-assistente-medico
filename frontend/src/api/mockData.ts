import type { ClinicalAlert } from '@/types/alert';
import type { Patient } from '@/types/patient';

/** Pacientes fictícios para protótipo (vários cenários de checkedInAt). */
export const MOCK_PATIENTS: Patient[] = [
  {
    id: 'P001',
    name: 'Ana Costa Silva',
    gender: 'Feminino',
    age: 34,
    mainCondition: 'Pneumonia comunitária',
    checkedInAt: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
  },
  {
    id: 'P002',
    name: 'Carlos Mendes',
    gender: 'Masculino',
    age: 62,
    mainCondition: 'ICC descompensada',
    checkedInAt: new Date(Date.now() - 20 * 60 * 60 * 1000).toISOString(),
  },
  {
    id: 'P003',
    name: 'Mariana Oliveira',
    gender: 'Feminino',
    age: 28,
    mainCondition: 'Crise asmática',
    checkedInAt: null,
  },
  {
    id: 'P004',
    name: 'Roberto Alves',
    gender: 'Masculino',
    age: 71,
    mainCondition: 'AVC isquêmico',
    checkedInAt: new Date(Date.now() - 30 * 60 * 1000).toISOString(),
  },
  {
    id: 'P005',
    name: 'Fernanda Rocha',
    gender: 'Feminino',
    age: 45,
    mainCondition: 'Pielonefrite',
    checkedInAt: new Date(Date.now() - 50 * 60 * 60 * 1000).toISOString(),
  },
  {
    id: 'P006',
    name: 'Lucas Pereira',
    gender: 'Masculino',
    age: 19,
    mainCondition: 'Trauma de membro inferior',
    checkedInAt: new Date(Date.now() - 11 * 60 * 60 * 1000).toISOString(),
  },
  {
    id: 'P007',
    name: 'Helena Duarte',
    gender: 'Feminino',
    age: 55,
    mainCondition: 'Sepse de foco urinário',
    checkedInAt: null,
  },
];

/** Alertas fictícios ligados a pacientes do mock. */
export const MOCK_ALERTS: ClinicalAlert[] = [
  {
    id: 'A1',
    patientId: 'P001',
    title: 'Hemocultura pendente',
    severity: 'warning',
    createdAt: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
    message: 'Coleta programada há 2h ainda não registrada no sistema.',
  },
  {
    id: 'A2',
    patientId: 'P002',
    title: 'Balanço hídrico',
    severity: 'info',
    createdAt: new Date(Date.now() - 5 * 60 * 60 * 1000).toISOString(),
    message: 'Revisar débito urinário nas últimas 8 horas.',
  },
  {
    id: 'A3',
    patientId: 'P004',
    title: 'PA fora da meta',
    severity: 'critical',
    createdAt: new Date(Date.now() - 25 * 60 * 1000).toISOString(),
    message: 'Última aferição acima do limite definido na conduta.',
  },
  {
    id: 'A4',
    patientId: 'P005',
    title: 'Exame de imagem',
    severity: 'info',
    createdAt: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
    message: 'TC de abdome aguardando laudo.',
  },
];
