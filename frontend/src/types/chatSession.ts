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
