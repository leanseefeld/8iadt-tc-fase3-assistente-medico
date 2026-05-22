/**
 * URL base da API REST quando o backend existir.
 * Todas as chamadas clinicas usam backend HTTP.
 */
export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api';

/** Lê o id do médico logado diretamente do localStorage (sem React). */
function getLoggedDoctorId(): string | null {
  try {
    return localStorage.getItem('assistenteMedico.authDoctorId');
  } catch {
    return null;
  }
}

/**
 * Wrapper fino sobre fetch que injeta `X-User-Id` automaticamente em todas as
 * requisições ao backend, usando o médico logado na sessão fake.
 * Assinatura idêntica ao fetch nativo — pode substituir fetch() diretamente.
 */
export function apiFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const doctorId = getLoggedDoctorId();
  if (!doctorId) {
    return fetch(input, init);
  }
  const headers = new Headers(init?.headers);
  headers.set('X-User-Id', doctorId);
  return fetch(input, { ...init, headers });
}
