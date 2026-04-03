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
}

const AppSessionContext = createContext<AppSessionContextValue | null>(null);

export function AppSessionProvider({ children }: { children: ReactNode }) {
  const [activePatientId, setActivePatientId] = useState<string | null>(null);
  const [admittedPatients, setAdmittedPatients] = useState<Patient[]>([]);
  const [unresolvedAlertCount, setUnresolvedAlertCount] = useState(0);
  const [pendingFlowReview, setPendingFlowReview] = useState(false);

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
    }),
    [
      activePatientId,
      admittedPatients,
      refreshAdmittedPatients,
      refreshAlertBadge,
      unresolvedAlertCount,
      pendingFlowReview,
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
