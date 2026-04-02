import {
  createContext,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import type { Patient } from '@/types/patient';
import { MOCK_PATIENTS } from '@/api/mockData';

export interface PatientContextValue {
  selectedPatient: Patient;
  setSelectedPatient: (patient: Patient) => void;
}

const PatientContext = createContext<PatientContextValue | null>(null);

export function PatientProvider({ children }: { children: ReactNode }) {
  const [selectedPatient, setSelectedPatient] = useState<Patient>(
    MOCK_PATIENTS[0]!,
  );

  const value = useMemo(
    () => ({ selectedPatient, setSelectedPatient }),
    [selectedPatient],
  );

  return (
    <PatientContext.Provider value={value}>{children}</PatientContext.Provider>
  );
}

export function usePatientContext(): PatientContextValue {
  const ctx = useContext(PatientContext);
  if (ctx == null) {
    throw new Error('usePatientContext deve ser usado dentro de PatientProvider');
  }
  return ctx;
}
