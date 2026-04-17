import { API_BASE_URL } from '@/api/client';
import type { Cid } from '@/types/domain';

const CACHE_TTL_MS = 5 * 60 * 1000;

let cache: Cid[] | null = null;
let cacheAt = 0;

export async function getCidListHttp(): Promise<Cid[]> {
  const now = Date.now();
  if (cache && now - cacheAt < CACHE_TTL_MS) {
    return cache;
  }

  const res = await fetch(`${API_BASE_URL}/cids`, {
    headers: { Accept: 'application/json' },
  });
  if (!res.ok) {
    throw new Error(`Falha ao buscar CIDs: HTTP ${res.status}`);
  }

  const body = (await res.json()) as { cids: Cid[] };
  cache = body.cids ?? [];
  cacheAt = now;
  return cache;
}

export function clearCidCache(): void {
  cache = null;
  cacheAt = 0;
}
