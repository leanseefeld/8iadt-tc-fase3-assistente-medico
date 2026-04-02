/** Formato alinhado ao contrato descrito em API_ASSUMPTIONS.md */

export type CheckInStatus = 'ok' | 'stale' | 'none';

export interface Patient {
  id: string;
  name: string;
  gender: string;
  age: number;
  mainCondition: string;
  /** ISO 8601; null = sem internação / sem check-in */
  checkedInAt: string | null;
}
