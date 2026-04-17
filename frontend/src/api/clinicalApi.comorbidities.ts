/**
 * Clinical API: Comorbidities endpoint (reference data for patient check-in)
 * HTTP transport for fetching comorbidity options from backend.
 */

const CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes

interface ComorbidityOption {
  code: string;
  label: string;
  category?: string;
}

export interface ComorbidititiesResponse {
  comorbidities: ComorbidityOption[];
}

// Simple in-memory cache with TTL
let cachedComorbidities: ComorbidititiesResponse | null = null;
let cacheTimestamp: number = 0;

/**
 * Fetch comorbidity options from backend.
 * Implements 5-minute in-memory cache.
 *
 * @returns Promise resolving to comorbidities response
 * @throws Error if backend returns error or network fails
 */
export async function getComorbidities(): Promise<ComorbidititiesResponse> {
  const now = Date.now();

  // Return cached if still valid
  if (cachedComorbidities && now - cacheTimestamp < CACHE_TTL_MS) {
    return cachedComorbidities;
  }

  try {
    const response = await fetch("/api/assistant/comorbidities");

    if (!response.ok) {
      throw new Error(
        `Comorbidities endpoint failed: ${response.status} ${response.statusText}`
      );
    }

    const contentType = response.headers.get("content-type");
    if (!contentType || !contentType.includes("application/json")) {
      const text = await response.text();
      throw new Error(
        `Invalid response content-type: ${contentType}. Response: ${text.substring(0, 100)}`
      );
    }

    const data = (await response.json()) as ComorbidititiesResponse;

    // Cache the result
    cachedComorbidities = data;
    cacheTimestamp = now;

    return data;
  } catch (error) {
    // If cache exists (even expired), use it as fallback
    if (cachedComorbidities) {
      console.warn("Using stale comorbidities cache due to fetch error:", error);
      return cachedComorbidities;
    }

    // No cache available and fetch failed
    throw new Error(`Failed to fetch comorbidities: ${error}`);
  }
}

/**
 * Clear cached comorbidities (useful for testing/forcing refresh).
 */
export function clearComorbidititiesCache(): void {
  cachedComorbidities = null;
  cacheTimestamp = 0;
}

export type { ComorbidityOption };
