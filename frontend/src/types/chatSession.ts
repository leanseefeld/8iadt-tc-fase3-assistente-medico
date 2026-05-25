import type { ExpandedMetaPanel } from '@/components/chat/AssistantMessageMeta';
import type { GuardrailStatus, MessageFeedbackRating } from '@/types/domain';

export type ChatSessionStatus = 'idle' | 'loading' | 'generating';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  streaming?: boolean;
  sources?: string[];
  reasoning?: string[];
  expandedPanel?: ExpandedMetaPanel | null;
  guardrailStatus?: GuardrailStatus;
  persistedMessageId?: string;
  feedbackRating?: MessageFeedbackRating;
  feedbackSubmitting?: boolean;
  /** Regeneração da última resposta em andamento. */
  regenerating?: boolean;
}

export interface ChatSession {
  sessionKey: string;
  threadId: string | null;
  patientId: string;
  messages: ChatMessage[];
  status: ChatSessionStatus;
}

export interface OptimisticConversationEntry {
  id: string;
  preview: string;
  generating: boolean;
  /** Navega para /chat sem thread (rascunho ainda sem id do servidor). */
  isPendingDraft: boolean;
}

export function truncatePreview(text: string, max = 80): string {
  const stripped = text.trim();
  if (stripped.length <= max) {
    return stripped;
  }
  return `${stripped.slice(0, max - 1)}…`;
}

export function pendingSessionKey(patientId: string): string {
  return `pending:${patientId}`;
}

export function resolveSessionKey(
  patientId: string,
  threadId: string | null,
): string {
  return threadId ?? pendingSessionKey(patientId);
}

/** Turno em andamento (nova mensagem ou regeneração) — não recarregar do servidor. */
export function sessionHasInFlightWork(session: ChatSession | undefined): boolean {
  if (!session) {
    return false;
  }
  if (session.status === 'generating') {
    return true;
  }
  return session.messages.some(
    (m) => m.regenerating || (m.role === 'assistant' && Boolean(m.streaming)),
  );
}

/**
 * Id local da mensagem que pode exibir 🔄, ou null.
 * Só a última mensagem da conversa, do assistente, persistida e sem geração ativa.
 */
export function resolveRegenerateMessageId(
  session: ChatSession | undefined,
): string | null {
  if (sessionHasInFlightWork(session)) {
    return null;
  }
  const last = session?.messages[session.messages.length - 1];
  if (!last || last.role !== 'assistant' || last.streaming) {
    return null;
  }
  return last.persistedMessageId ? last.id : null;
}

/** Mensagem com stream ou regeneração ainda em andamento. */
export function messageIsInFlight(msg: ChatMessage): boolean {
  return Boolean(msg.regenerating || (msg.role === 'assistant' && msg.streaming));
}

/** Prefere meta da resposta agregada; senão mantém a recebida via SSE durante o stream. */
export function mergeStreamMeta(
  fromResponse: string[] | undefined,
  fromMessage: string[] | undefined,
): string[] | undefined {
  if (fromResponse && fromResponse.length > 0) {
    return fromResponse;
  }
  if (fromMessage && fromMessage.length > 0) {
    return fromMessage;
  }
  return fromResponse ?? fromMessage;
}
