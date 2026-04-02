import type { CheckInStatus } from '@/types/patient';

const TWELVE_HOURS_MS = 12 * 60 * 60 * 1000;

/**
 * Regra de apresentação do indicador de check-in (janela móvel de 12 horas):
 * - ok (verde): há check-in e passaram no máximo 12h desde checkedInAt
 * - stale (amarelo): há check-in e passaram mais de 12h
 * - none (cinza): sem check-in (checkedInAt nulo)
 */
export function getCheckInStatus(checkedInAt: string | null): CheckInStatus {
  if (checkedInAt == null || checkedInAt === '') {
    return 'none';
  }
  const t = Date.parse(checkedInAt);
  if (Number.isNaN(t)) {
    return 'none';
  }
  const elapsed = Date.now() - t;
  if (elapsed <= TWELVE_HOURS_MS) {
    return 'ok';
  }
  return 'stale';
}
