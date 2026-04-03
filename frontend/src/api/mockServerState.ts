import type { Alert } from '@/types/alert';
import type { Patient } from '@/types/domain';

export interface MockServerState {
  patients: Patient[];
  alerts: Alert[];
}

function initialAlerts(): Alert[] {
  return [
    {
      id: 'a-01',
      patientId: 'system',
      severity: 'info',
      category: 'system',
      message: 'Sistema iniciado. Aguardando admissão de pacientes.',
      team: 'all',
      createdAt: new Date().toISOString(),
      resolved: false,
    },
  ];
}

export const mockServerState: MockServerState = {
  patients: [],
  alerts: initialAlerts(),
};

/** Útil em testes ou ao reiniciar a demo. */
export function resetMockServer(): void {
  mockServerState.patients = [];
  mockServerState.alerts = initialAlerts();
}
