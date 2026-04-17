import type { Exam, Patient, SuggestedActionItem } from '@/types/domain';

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
    | 'comorbidities'
    | 'vitalSigns'
  >
> & {
  currentMedications?: string[];
  exams?: Partial<Exam>[];
  suggestedItems?: Partial<SuggestedActionItem>[];
};
