import { API_BASE_URL } from '@/api/client';
import type { SuggestedActionItem } from '@/types/domain';

export async function createSuggestedItemHttp(
  patientId: string,
  input: Pick<SuggestedActionItem, 'type' | 'description'>,
): Promise<SuggestedActionItem> {
  const res = await fetch(`${API_BASE_URL}/patients/${patientId}/suggested-items`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    throw new Error(`Falha ao criar ação sugerida: HTTP ${res.status}`);
  }
  return ((await res.json()) as { item: SuggestedActionItem }).item;
}

export async function patchSuggestedItemHttp(
  patientId: string,
  itemId: string,
  patch: Partial<Pick<SuggestedActionItem, 'status' | 'description'>>,
): Promise<SuggestedActionItem> {
  const res = await fetch(`${API_BASE_URL}/patients/${patientId}/suggested-items/${itemId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(patch),
  });
  if (!res.ok) {
    throw new Error(`Falha ao atualizar ação sugerida: HTTP ${res.status}`);
  }
  return ((await res.json()) as { item: SuggestedActionItem }).item;
}
