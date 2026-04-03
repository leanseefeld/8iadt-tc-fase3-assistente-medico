/** DTO alinhado a API_ASSUMPTIONS.md */

export type AlertSeverity = 'critical' | 'moderate' | 'info';

export type AlertCategory = 'exam' | 'medication' | 'clinical' | 'system';

export type AlertTeam = 'doctors' | 'nursing' | 'pharmacy' | 'all';

export interface Alert {
  id: string;
  patientId: string;
  severity: AlertSeverity;
  category: AlertCategory;
  message: string;
  team: AlertTeam;
  createdAt: string;
  resolved: boolean;
}
