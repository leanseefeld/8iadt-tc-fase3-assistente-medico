export type AlertSeverity = 'info' | 'warning' | 'critical';

export interface ClinicalAlert {
  id: string;
  patientId: string;
  title: string;
  severity: AlertSeverity;
  /** ISO 8601 */
  createdAt: string;
  message: string;
}
