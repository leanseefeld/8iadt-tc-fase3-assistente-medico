/**
 * Autenticação fake para o protótipo: compara usuário e senha com a lista mockada.
 * Não substitui OAuth/JWT nem armazenamento seguro.
 */

import type { MockDoctor } from '@/mocks/internal/doctors';
import { MOCK_DOCTORS } from '@/mocks/internal/doctors';

export const AUTH_DOCTOR_STORAGE_KEY = 'assistenteMedico.authDoctorId';

/** Tenta credenciais e devolve o médico ou null. */
export function authenticateFake(
  username: string,
  password: string,
): MockDoctor | null {
  const u = username.trim().toLowerCase();
  const p = password;
  return (
    MOCK_DOCTORS.find(
      (d) => d.username.toLowerCase() === u && d.password === p,
    ) ?? null
  );
}
