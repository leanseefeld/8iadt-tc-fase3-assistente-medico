import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import {
  getPatientsMock,
  getUnresolvedAlertCountMock,
} from '@/api/clinicalApi';
import type { Patient } from '@/types/domain';
import { MOCK_DOCTORS } from '@/mocks/internal/doctors';

const ACTIVE_DOCTOR_STORAGE_KEY = 'assistenteMedico.activeDoctorId';

export interface AppSessionContextValue {
  activePatientId: string | null;
  setActivePatientId: (id: string | null) => void;
  admittedPatients: Patient[];
  refreshAdmittedPatients: () => Promise<void>;
  refreshAlertBadge: () => Promise<void>;
  unresolvedAlertCount: number;
  /** Após editar CID: banner na Página 3 até o médico reexecutar o fluxo */
  pendingFlowReview: boolean;
  setPendingFlowReview: (v: boolean) => void;
  /** Login fake: médico selecionado na barra superior */
  activeDoctorId: string;
  setActiveDoctorId: (id: string) => void;
  activeDoctor: (typeof MOCK_DOCTORS)[number] | null;
}

const AppSessionContext = createContext<AppSessionContextValue | null>(null);

export function AppSessionProvider({ children }: { children: ReactNode }) {
  const [activePatientId, setActivePatientId] = useState<string | null>(null);
  const [admittedPatients, setAdmittedPatients] = useState<Patient[]>([]);
  const [unresolvedAlertCount, setUnresolvedAlertCount] = useState(0);
  const [pendingFlowReview, setPendingFlowReview] = useState(false);
  const [activeDoctorId, setActiveDoctorIdState] = useState<string>(() => {
    if (MOCK_DOCTORS.length === 0) {
      return '';
    }
    try {
      const stored = localStorage.getItem(ACTIVE_DOCTOR_STORAGE_KEY);
      if (stored && MOCK_DOCTORS.some((d) => d.id === stored)) {
        return stored;
      }
    } catch {
      /* ignore */
    }
    return MOCK_DOCTORS[0].id;
  });

  const setActiveDoctorId = useCallback((id: string) => {
    setActiveDoctorIdState(id);
    try {
      localStorage.setItem(ACTIVE_DOCTOR_STORAGE_KEY, id);
    } catch {
      /* ignore */
    }
  }, []);

  const activeDoctor = useMemo(() => {
    return MOCK_DOCTORS.find((d) => d.id === activeDoctorId) ?? MOCK_DOCTORS[0] ?? null;
  }, [activeDoctorId]);

  const refreshAdmittedPatients = useCallback(async () => {
    const list = await getPatientsMock({ status: 'admitted' });
    setAdmittedPatients(list);
    setActivePatientId((current) => {
      if (current && list.some((p) => p.id === current)) {
        return current;
      }
      return list[0]?.id ?? null;
    });
  }, []);

  const refreshAlertBadge = useCallback(async () => {
    setUnresolvedAlertCount(await getUnresolvedAlertCountMock());
  }, []);

  useEffect(() => {
    void refreshAdmittedPatients();
    void refreshAlertBadge();
  }, [refreshAdmittedPatients, refreshAlertBadge]);

  const value = useMemo(
    () => ({
      activePatientId,
      setActivePatientId,
      admittedPatients,
      refreshAdmittedPatients,
      refreshAlertBadge,
      unresolvedAlertCount,
      pendingFlowReview,
      setPendingFlowReview,
      activeDoctorId,
      setActiveDoctorId,
      activeDoctor,
    }),
    [
      activePatientId,
      admittedPatients,
      refreshAdmittedPatients,
      refreshAlertBadge,
      unresolvedAlertCount,
      pendingFlowReview,
      activeDoctorId,
      setActiveDoctorId,
      activeDoctor,
    ],
  );

  return (
    <AppSessionContext.Provider value={value}>
      {children}
    </AppSessionContext.Provider>
  );
}

export function useAppSession(): AppSessionContextValue {
  const ctx = useContext(AppSessionContext);
  if (ctx == null) {
    throw new Error('useAppSession deve ser usado dentro de AppSessionProvider');
  }
  return ctx;
}
