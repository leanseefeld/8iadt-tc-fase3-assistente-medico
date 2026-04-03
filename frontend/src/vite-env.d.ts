/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Quando `'true'` ou `'1'`, usa `clinicalApi.http.ts` (fetch).
   * Omitido ou outro valor: `clinicalApi.memory.ts` (in-memory).
   */
  readonly VITE_CLINICAL_API_HTTP?: string;
}
