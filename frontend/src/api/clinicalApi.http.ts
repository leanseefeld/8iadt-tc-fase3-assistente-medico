/**
 * Transporte HTTP para endpoints do assistente.
 */
import { API_BASE_URL } from '@/api/client';
import type { ChatResponse, DecisionFlowResponse } from '@/types/domain';
import {
  consumeAssistantChatSse,
  type ChatStreamHandlers,
} from '@/api/sseChat';

export type { ChatStreamHandlers };

/** Turnos anteriores à `message` atual (contrato alinhado ao backend). */
export type AssistantMessageHistoryItem = {
  role: 'user' | 'assistant';
  content: string;
};

export type AssistantChatRequestOptions = ChatStreamHandlers & {
  messageHistory?: AssistantMessageHistoryItem[];
};

export async function postAssistantChatMock(
  patientId: string,
  message: string,
  options?: AssistantChatRequestOptions,
): Promise<ChatResponse> {
  const url = `${API_BASE_URL}/assistant/chat`;
  const messageHistory = options?.messageHistory;
  const body = JSON.stringify({
    patientId,
    message,
    ...(messageHistory?.length
      ? { messageHistory: messageHistory }
      : {}),
  });
  const useSse = Boolean(
    options && (options.onToken != null || options.onMeta != null),
  );

  if (useSse) {
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      body,
    });
    if (!res.ok) {
      const detail = await parseHttpErrorDetail(res);
      options?.onError?.(detail);
      throw new Error(detail);
    }
    return consumeAssistantChatSse(res, options);
  }

  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body,
  });
  if (!res.ok) {
    throw new Error(await parseHttpErrorDetail(res));
  }
  return (await res.json()) as ChatResponse;
}

async function parseHttpErrorDetail(res: Response): Promise<string> {
  const fallback = `Erro HTTP ${res.status}`;
  const raw = await res.text();
  if (!raw.trim()) {
    return fallback;
  }
  try {
    const j = JSON.parse(raw) as { detail?: unknown };
    if (typeof j.detail === 'string') {
      return j.detail;
    }
  } catch {
    /* corpo não é JSON */
  }
  return raw.slice(0, 280);
}

export async function postAssistantDecisionFlowMock(
  patientId: string,
): Promise<DecisionFlowResponse> {
  const res = await fetch(`${API_BASE_URL}/assistant/decision-flow`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify({ patientId }),
  });
  if (!res.ok) {
    throw new Error(await parseHttpErrorDetail(res));
  }
  return (await res.json()) as DecisionFlowResponse;
}
