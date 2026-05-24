import type { Cid } from '@/types/domain';

/** Exibe CID do paciente ou mensagem quando não informado na admissão. */
export function formatPatientCid(cid: Cid): string {
  const code = (cid.code ?? '').trim();
  const label = (cid.label ?? '').trim();
  if (!code && !label) {
    return 'CID não informado';
  }
  if (!code) {
    return label;
  }
  if (!label) {
    return code;
  }
  return `${code} — ${label}`;
}

export function hasPatientCid(cid: Cid): boolean {
  return Boolean((cid.code ?? '').trim());
}
