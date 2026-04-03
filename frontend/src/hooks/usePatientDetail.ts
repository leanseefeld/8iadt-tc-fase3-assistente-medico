import { useCallback, useEffect, useState } from 'react';
import { getPatientByIdMock } from '@/api/clinicalApi';
import type { Patient } from '@/types/domain';

export function usePatientDetail(patientId: string | null): {
  patient: Patient | null;
  loading: boolean;
  refetch: () => Promise<void>;
} {
  const [patient, setPatient] = useState<Patient | null>(null);
  const [loading, setLoading] = useState(false);

  const refetch = useCallback(async () => {
    if (patientId == null) {
      setPatient(null);
      return;
    }
    setLoading(true);
    const p = await getPatientByIdMock(patientId);
    setPatient(p);
    setLoading(false);
  }, [patientId]);

  useEffect(() => {
    void refetch();
  }, [refetch]);

  return { patient, loading, refetch };
}
