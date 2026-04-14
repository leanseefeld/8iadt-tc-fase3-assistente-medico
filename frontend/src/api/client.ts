/**
 * URL base da API REST quando o backend existir.
 * Em protótipo as chamadas passam por clinicalApi (memória por padrão).
 */
export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api';
