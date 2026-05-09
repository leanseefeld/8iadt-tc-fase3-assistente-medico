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
import { AUTH_DOCTOR_STORAGE_KEY, authenticateFake } from '@/auth/fakeAuth';
import type { MockDoctor } from '@/mocks/internal/doctors';
import { MOCK_DOCTORS } from '@/mocks/internal/doctors';
import type { Patient } from '@/types/domain';

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
  /** Médico logado (auth fake); null fora da sessão. */
  activeDoctor: MockDoctor | null;
  login: (username: string, password: string) => MockDoctor | null;
  logout: () => void;
}

const AppSessionContext = createContext<AppSessionContextValue | null>(null);

export function AppSessionProvider({ children }: { children: ReactNode }) {
  const [activePatientId, setActivePatientId] = useState<string | null>(null);
  const [admittedPatients, setAdmittedPatients] = useState<Patient[]>([]);
  const [unresolvedAlertCount, setUnresolvedAlertCount] = useState(0);
  const [pendingFlowReview, setPendingFlowReview] = useState(false);
  const [authDoctorId, setAuthDoctorId] = useState<string | null>(() => {
    if (MOCK_DOCTORS.length === 0) {
      return null;
    }
    try {
      const stored = localStorage.getItem(AUTH_DOCTOR_STORAGE_KEY);
      if (stored && MOCK_DOCTORS.some((d) => d.id === stored)) {
        return stored;
      }
    } catch {
      /* ignore */
    }
    return null;
  });

  const login = useCallback((username: string, password: string): MockDoctor | null => {
    const doc = authenticateFake(username, password);
    if (doc == null) {
      return null;
    }
    setAuthDoctorId(doc.id);
    try {
      localStorage.setItem(AUTH_DOCTOR_STORAGE_KEY, doc.id);
    } catch {
      /* ignore */
    }
    return doc;
  }, []);

  const logout = useCallback(() => {
    setAuthDoctorId(null);
    try {
      localStorage.removeItem(AUTH_DOCTOR_STORAGE_KEY);
    } catch {
      /* ignore */
    }
  }, []);

  const activeDoctor = useMemo((): MockDoctor | null => {
    if (authDoctorId == null) {
      return null;
    }
    return MOCK_DOCTORS.find((d) => d.id === authDoctorId) ?? null;
  }, [authDoctorId]);

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
      activeDoctor,
      login,
      logout,
    }),
    [
      activePatientId,
      admittedPatients,
      refreshAdmittedPatients,
      refreshAlertBadge,
      unresolvedAlertCount,
      pendingFlowReview,
      activeDoctor,
      login,
      logout,
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
