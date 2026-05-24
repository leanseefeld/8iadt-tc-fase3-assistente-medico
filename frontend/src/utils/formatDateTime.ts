/**
 * Converte ISO da API em Date.
 * Valores sem fuso (ex.: `2026-05-24T18:30:00`) são UTC no backend SQLite.
 */
export function parseApiDateTime(iso: string): Date {
  const trimmed = iso.trim();
  if (!trimmed) {
    return new Date(Number.NaN);
  }
  const hasTimezone = /[Zz]$/.test(trimmed) || /[+-]\d{2}:\d{2}$/.test(trimmed);
  return new Date(hasTimezone ? trimmed : `${trimmed}Z`);
}

/** Data/hora curta no fuso local do usuário (pt-BR). */
export function formatLocalDateTime(iso: string): string {
  const d = parseApiDateTime(iso);
  if (Number.isNaN(d.getTime())) {
    return '';
  }
  return d.toLocaleString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}
