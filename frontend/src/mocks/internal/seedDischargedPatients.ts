/**
 * Pacientes mock com alta pré-carregados para busca/readmissão no check-in.
 */
import type { Patient } from '@/types/domain';

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString();
}

function baseVitals(): Patient['vitalSigns'] {
  const now = new Date().toISOString();
  return {
    bloodPressure: '120/80',
    temperature: 36.5,
    oxygenSaturation: 97,
    heartRate: 72,
    updatedAt: now,
  };
}

/** Clona lista inicial (evita mutação partilhada entre resets). */
export function buildSeedDischargedPatients(): Patient[] {
  return [
    {
      id: 'mock-disch-01',
      name: 'Maria Oliveira',
      age: 62,
      sex: 'F',
      status: 'discharged',
      admittedAt: isoDaysAgo(14),
      cid: { code: 'L40.5', label: 'Artrite Psoriásica' },
      chiefComplaint: 'Dor em articulações e rigidez matinal',
      comorbidities: ['HAS'],
      currentMedications: ['Losartana 50mg'],
      vitalSigns: baseVitals(),
      exams: [],
      suggestedItems: [],
      agentLog: [],
    },
    {
      id: 'mock-disch-02',
      name: 'Carlos Mendes',
      age: 41,
      sex: 'M',
      status: 'discharged',
      admittedAt: isoDaysAgo(30),
      cid: { code: 'T81.4', label: 'Infecção pós-procedimento cirúrgico' },
      chiefComplaint: 'Febre e dor no sítio cirúrgico',
      comorbidities: ['DM2'],
      currentMedications: ['Warfarina 5mg', 'Ciprofloxacino 500mg'],
      vitalSigns: baseVitals(),
      exams: [],
      suggestedItems: [],
      agentLog: [],
    },
    {
      id: 'mock-disch-03',
      name: 'Ana Costa',
      age: 54,
      sex: 'F',
      status: 'discharged',
      admittedAt: isoDaysAgo(7),
      cid: { code: 'A41.9', label: 'Sepse não especificada' },
      chiefComplaint: 'Hipotensão e taquicardia',
      comorbidities: ['IRC'],
      currentMedications: [],
      vitalSigns: baseVitals(),
      exams: [],
      suggestedItems: [],
      agentLog: [],
    },
    {
      id: 'mock-disch-04',
      name: 'Pedro Alves',
      age: 58,
      sex: 'M',
      status: 'discharged',
      admittedAt: isoDaysAgo(45),
      cid: { code: 'E11.9', label: 'Diabetes Mellitus tipo 2 sem complicações' },
      chiefComplaint: 'Hipoglicemia leve em jejum',
      comorbidities: ['HAS', 'Obesidade'],
      currentMedications: ['Metformina'],
      vitalSigns: baseVitals(),
      exams: [],
      suggestedItems: [],
      agentLog: [],
    },
    {
      id: 'mock-disch-05',
      name: 'Roberto Farias',
      age: 72,
      sex: 'M',
      status: 'discharged',
      admittedAt: isoDaysAgo(90),
      cid: { code: 'I50.0', label: 'Insuficiência Cardíaca Congestiva' },
      chiefComplaint: 'Dispneia aos esforços',
      comorbidities: ['HAS', 'DM2'],
      currentMedications: ['Enalapril', 'Furosemida'],
      vitalSigns: baseVitals(),
      exams: [],
      suggestedItems: [],
      agentLog: [],
    },
  ];
}
