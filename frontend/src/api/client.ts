/**
 * URL base da API REST quando o backend existir.
 * Em protótipo as chamadas passam pelos mocks em mockApi.ts.
 */
export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:3000/api';
