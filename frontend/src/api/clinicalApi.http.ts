/**
 * Transporte HTTP para endpoints do assistente.
 */
import { apiFetch, API_BASE_URL } from '@/api/client';
import type {
  ChatResponse,
  ConversationArchiveResponse,
  ConversationListResponse,
  ConversationMessagesResponse,
  DecisionFlowResponse,
  MessageFeedbackPatchResponse,
  MessageFeedbackRating,
} from '@/types/domain';
import {
  consumeAssistantChatSse,
  type ChatStreamHandlers,
} from '@/api/sseChat';

export type { ChatStreamHandlers };

export type AssistantChatRequestOptions = ChatStreamHandlers & {
  /** Memória de conversa no servidor; omitir na primeira mensagem da sessão. */
  threadId?: string;
};

export async function postAssistantChatMock(
  patientId: string,
  message: string,
  options?: AssistantChatRequestOptions,
): Promise<ChatResponse> {
  const url = `${API_BASE_URL}/assistant/chat`;
  const body = JSON.stringify({
    patientId,
    message,
    ...(options?.threadId ? { threadId: options.threadId } : {}),
  });
  const useSse = Boolean(
    options && (options.onToken != null || options.onMeta != null),
  );

  if (useSse) {
    const res = await apiFetch(url, {
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

  const res = await apiFetch(url, {
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

export async function patchAssistantMessageFeedback(
  conversationId: string,
  messageId: string,
  feedbackRating: MessageFeedbackRating | null,
): Promise<MessageFeedbackPatchResponse> {
  const res = await apiFetch(
    `${API_BASE_URL}/assistant/conversations/${conversationId}/messages/${messageId}`,
    {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify({ feedbackRating }),
    },
  );
  if (!res.ok) {
    throw new Error(await parseHttpErrorDetail(res));
  }
  return (await res.json()) as MessageFeedbackPatchResponse;
}

export async function listAssistantConversations(
  patientId: string,
): Promise<ConversationListResponse> {
  const url = new URL(`${API_BASE_URL}/assistant/conversations`);
  url.searchParams.set('patientId', patientId);
  const res = await apiFetch(url.toString(), {
    headers: { Accept: 'application/json' },
  });
  if (!res.ok) {
    throw new Error(await parseHttpErrorDetail(res));
  }
  return (await res.json()) as ConversationListResponse;
}

export async function getAssistantConversationMessages(
  conversationId: string,
): Promise<ConversationMessagesResponse> {
  const res = await apiFetch(
    `${API_BASE_URL}/assistant/conversations/${conversationId}/messages`,
    { headers: { Accept: 'application/json' } },
  );
  if (!res.ok) {
    throw new Error(await parseHttpErrorDetail(res));
  }
  return (await res.json()) as ConversationMessagesResponse;
}

export async function archiveAssistantConversation(
  conversationId: string,
): Promise<ConversationArchiveResponse> {
  const res = await apiFetch(
    `${API_BASE_URL}/assistant/conversations/${conversationId}/archive`,
    {
      method: 'PATCH',
      headers: { Accept: 'application/json' },
    },
  );
  if (!res.ok) {
    throw new Error(await parseHttpErrorDetail(res));
  }
  return (await res.json()) as ConversationArchiveResponse;
}

export async function postAssistantDecisionFlowMock(
  patientId: string,
): Promise<DecisionFlowResponse> {
  const res = await apiFetch(`${API_BASE_URL}/assistant/decision-flow`, {
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
