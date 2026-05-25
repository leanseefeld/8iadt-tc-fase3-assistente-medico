import type { Exam, Patient } from '@/types/domain';

export type ReAdmitOverrides = {
  observations?: string;
  comorbidities?: string[];
  currentMedications?: string;
};

export type PatchPatientBody = Partial<
  Pick<
    Patient,
    | 'cid'
    | 'status'
    | 'observations'
    | 'gender'
    | 'symptoms'
    | 'comorbidities'
    | 'vitalSigns'
  >
> & {
  currentMedications?: string[];
  exams?: Partial<Exam>[];
};
