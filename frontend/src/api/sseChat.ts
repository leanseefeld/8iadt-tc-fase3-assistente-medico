/**
 * Consumidor mínimo de SSE (POST + fetch) para o endpoint de chat.
 * Formato alinhado a sse-starlette: blocos separados por linha em branco.
 */

import type { ChatResponse } from '@/types/domain';

export interface ChatStreamHandlers {
  onToken?: (delta: string) => void;
  onMeta?: (sources: string[], reasoning: string[]) => void;
  onError?: (message: string) => void;
}

/** Normaliza quebras de linha para facilitar o split por bloco SSE. */
function normalizeNewlines(s: string): string {
  return s.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
}

/** Extrai event e data de um bloco SSE (pode haver várias linhas ``data:``). */
function parseSseBlock(block: string): { event: string; data: string } {
  let event = 'message';
  const dataLines: string[] = [];
  for (const rawLine of block.split('\n')) {
    const line = rawLine.trimEnd();
    if (line.startsWith('event:')) {
      event = line.slice(6).trimStart();
    } else if (line.startsWith('data:')) {
      let rest = line.slice(5);
      if (rest.startsWith(' ')) {
        rest = rest.slice(1);
      }
      dataLines.push(rest);
    }
  }
  return { event, data: dataLines.join('\n') };
}

/**
 * Lê o corpo da resposta como stream SSE e devolve o ChatResponse agregado.
 * Emite callbacks conforme eventos ``token``, ``sources``, ``reasoning``, ``error``.
 */
export async function consumeAssistantChatSse(
  response: Response,
  handlers?: ChatStreamHandlers,
): Promise<ChatResponse> {
  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('Resposta sem corpo legível.');
  }

  const decoder = new TextDecoder();
  let carry = '';
  let text = '';
  let sources: string[] = [];
  let reasoning: string[] = [];

  // --- Loop: acumula bytes, fatia em blocos SSE terminados em linha em branco ---
  for (;;) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    carry += decoder.decode(value, { stream: true });
    carry = normalizeNewlines(carry);
    const blocks = carry.split('\n\n');
    carry = blocks.pop() ?? '';
    for (const block of blocks) {
      if (!block.trim()) {
        continue;
      }
      const { event, data } = parseSseBlock(block);
      let payload: Record<string, unknown> = {};
      if (data) {
        try {
          payload = JSON.parse(data) as Record<string, unknown>;
        } catch {
          handlers?.onError?.('Resposta inválida do servidor (JSON).');
          throw new Error('JSON inválido no stream SSE.');
        }
      }
      if (event === 'token') {
        const content = typeof payload.content === 'string' ? payload.content : '';
        if (content) {
          text += content;
          handlers?.onToken?.(content);
        }
      } else if (event === 'sources') {
        const s = payload.sources;
        sources = Array.isArray(s) ? (s as string[]) : [];
        handlers?.onMeta?.(sources, reasoning);
      } else if (event === 'reasoning') {
        const steps = payload.steps;
        reasoning = Array.isArray(steps) ? (steps as string[]) : [];
        handlers?.onMeta?.(sources, reasoning);
      } else if (event === 'error') {
        const detail =
          typeof payload.detail === 'string' ? payload.detail : 'Erro no assistente.';
        handlers?.onError?.(detail);
        throw new Error(detail);
      }
    }
  }

  return { text, sources, reasoning };
}
