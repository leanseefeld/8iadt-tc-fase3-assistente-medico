import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import {
  getAssistantConversationMessages,
  patchAssistantMessageFeedback,
  postAssistantChatMock,
} from '@/api/clinicalApi';
import { useConversationRefresh } from '@/context/ConversationRefreshContext';
import { useToast } from '@/context/ToastContext';
import type { ConversationMessageDto, MessageFeedbackRating } from '@/types/domain';
import type { ChatMessage, ChatSession, OptimisticConversationEntry } from '@/types/chatSession';
import {
  pendingSessionKey,
  resolveSessionKey,
  truncatePreview,
} from '@/types/chatSession';

interface ChatSessionContextValue {
  version: number;
  getSession: (patientId: string, threadId: string | null) => ChatSession;
  ensureSessionLoaded: (patientId: string, threadId: string | null) => Promise<void>;
  sendMessage: (
    patientId: string,
    threadId: string | null,
    text: string,
  ) => Promise<string | null>;
  isThreadGenerating: (threadId: string) => boolean;
  getOptimisticSidebarEntries: (
    patientId: string,
    apiConversationIds: Set<string>,
  ) => OptimisticConversationEntry[];
  patchMessage: (
    patientId: string,
    threadId: string | null,
    messageId: string,
    patch: Partial<ChatMessage>,
  ) => void;
  updateMessages: (
    patientId: string,
    threadId: string | null,
    updater: (messages: ChatMessage[]) => ChatMessage[],
  ) => void;
  submitFeedback: (
    patientId: string,
    threadId: string | null,
    localMessageId: string,
    clicked: MessageFeedbackRating,
  ) => Promise<void>;
  clearPendingSession: (patientId: string) => void;
}

const ChatSessionContext = createContext<ChatSessionContextValue | null>(null);

function mapPersistedMessages(rows: ConversationMessageDto[]): ChatMessage[] {
  return rows.map((row) => ({
    id: row.id,
    role: row.author,
    text: row.content,
    sources: row.sources ?? undefined,
    reasoning: row.reasoningSteps ?? undefined,
    persistedMessageId: row.author === 'assistant' ? row.id : undefined,
    feedbackRating: row.feedbackRating ?? undefined,
  }));
}

function emptySession(patientId: string, threadId: string | null): ChatSession {
  const sessionKey = resolveSessionKey(patientId, threadId);
  return {
    sessionKey,
    threadId,
    patientId,
    messages: [],
    status: 'idle',
  };
}

function patchAssistantMessage(
  messages: ChatMessage[],
  assistantId: string,
  patch: Partial<ChatMessage>,
): ChatMessage[] {
  return messages.map((msg) =>
    msg.id === assistantId ? { ...msg, ...patch } : msg,
  );
}

export function ChatSessionProvider({ children }: { children: ReactNode }) {
  const sessionsRef = useRef<Map<string, ChatSession>>(new Map());
  const [version, setVersion] = useState(0);
  const { refreshConversations } = useConversationRefresh();
  const { showToast } = useToast();

  const bump = useCallback(() => {
    setVersion((v) => v + 1);
  }, []);

  const getSession = useCallback(
    (patientId: string, threadId: string | null): ChatSession => {
      if (threadId) {
        return sessionsRef.current.get(threadId) ?? emptySession(patientId, threadId);
      }
      const pending = sessionsRef.current.get(pendingSessionKey(patientId));
      if (pending?.status === 'generating') {
        return pending;
      }
      return emptySession(patientId, null);
    },
    [],
  );

  const setSession = useCallback(
    (key: string, session: ChatSession) => {
      sessionsRef.current.set(key, session);
      bump();
    },
    [bump],
  );

  const updateSession = useCallback(
    (key: string, updater: (session: ChatSession) => ChatSession) => {
      const current =
        sessionsRef.current.get(key) ?? emptySession('', key.startsWith('pending:') ? null : key);
      const next = updater(current);
      sessionsRef.current.set(key, next);
      bump();
    },
    [bump],
  );

  const migratePendingToThread = useCallback(
    (patientId: string, threadId: string) => {
      const pk = pendingSessionKey(patientId);
      const pending = sessionsRef.current.get(pk);
      if (!pending) {
        return;
      }
      sessionsRef.current.set(threadId, {
        ...pending,
        sessionKey: threadId,
        threadId,
      });
      sessionsRef.current.delete(pk);
      bump();
    },
    [bump],
  );

  const isThreadGenerating = useCallback((threadId: string): boolean => {
    return sessionsRef.current.get(threadId)?.status === 'generating';
  }, []);

  const getOptimisticSidebarEntries = useCallback(
    (patientId: string, apiConversationIds: Set<string>): OptimisticConversationEntry[] => {
      const entries: OptimisticConversationEntry[] = [];
      const seen = new Set<string>();

      const pushEntry = (entry: OptimisticConversationEntry) => {
        if (seen.has(entry.id) || apiConversationIds.has(entry.id)) {
          return;
        }
        seen.add(entry.id);
        entries.push(entry);
      };

      const pending = sessionsRef.current.get(pendingSessionKey(patientId));
      if (pending) {
        const firstUser = pending.messages.find((m) => m.role === 'user');
        if (firstUser?.text.trim()) {
          pushEntry({
            id: pendingSessionKey(patientId),
            preview: truncatePreview(firstUser.text),
            generating: pending.status === 'generating',
            isPendingDraft: true,
          });
        }
      }

      for (const session of sessionsRef.current.values()) {
        if (session.patientId !== patientId || !session.threadId) {
          continue;
        }
        if (apiConversationIds.has(session.threadId)) {
          continue;
        }
        const firstUser = session.messages.find((m) => m.role === 'user');
        if (!firstUser?.text.trim()) {
          continue;
        }
        pushEntry({
          id: session.threadId,
          preview: truncatePreview(firstUser.text),
          generating: session.status === 'generating',
          isPendingDraft: false,
        });
      }

      return entries;
    },
    [],
  );

  const ensureSessionLoaded = useCallback(
    async (patientId: string, threadId: string | null) => {
      if (!threadId) {
        return;
      }
      const existing = sessionsRef.current.get(threadId);
      if (existing?.status === 'generating') {
        return;
      }

      setSession(threadId, {
        ...(existing ?? emptySession(patientId, threadId)),
        patientId,
        threadId,
        sessionKey: threadId,
        status: 'loading',
      });

      try {
        const res = await getAssistantConversationMessages(threadId);
        if (res.patientId !== patientId) {
          sessionsRef.current.delete(threadId);
          bump();
          throw new Error('wrong_patient');
        }
        setSession(threadId, {
          sessionKey: threadId,
          threadId,
          patientId,
          messages: mapPersistedMessages(res.messages),
          status: 'idle',
        });
      } catch {
        sessionsRef.current.delete(threadId);
        bump();
        throw new Error('load_failed');
      }
    },
    [bump, setSession],
  );

  const patchMessage = useCallback(
    (
      patientId: string,
      threadId: string | null,
      messageId: string,
      patch: Partial<ChatMessage>,
    ) => {
      const key = resolveSessionKey(patientId, threadId);
      updateSession(key, (session) => ({
        ...session,
        messages: session.messages.map((msg) =>
          msg.id === messageId ? { ...msg, ...patch } : msg,
        ),
      }));
    },
    [updateSession],
  );

  const updateMessages = useCallback(
    (
      patientId: string,
      threadId: string | null,
      updater: (messages: ChatMessage[]) => ChatMessage[],
    ) => {
      const key = resolveSessionKey(patientId, threadId);
      updateSession(key, (session) => ({
        ...session,
        messages: updater(session.messages),
      }));
    },
    [updateSession],
  );

  const sendMessage = useCallback(
    async (
      patientId: string,
      threadId: string | null,
      text: string,
    ): Promise<string | null> => {
      const trimmed = text.trim();
      if (!trimmed) {
        return threadId;
      }

      let activeKey = resolveSessionKey(patientId, threadId);
      const existing =
        sessionsRef.current.get(activeKey) ??
        emptySession(patientId, threadId);
      const assistantId = `a-${Date.now()}`;

      setSession(activeKey, {
        ...existing,
        patientId,
        threadId,
        sessionKey: activeKey,
        status: 'generating',
        messages: [
          ...existing.messages,
          { id: `u-${Date.now()}`, role: 'user', text: trimmed },
          { id: assistantId, role: 'assistant', text: '', streaming: true },
        ],
      });

      try {
        const res = await postAssistantChatMock(patientId, trimmed, {
          threadId: threadId ?? undefined,
          onToken: (delta) => {
            const key = activeKey;
            const session = sessionsRef.current.get(key);
            if (!session) {
              return;
            }
            sessionsRef.current.set(key, {
              ...session,
              messages: patchAssistantMessage(session.messages, assistantId, {
                text:
                  (session.messages.find((m) => m.id === assistantId)?.text ?? '') +
                  delta,
              }),
            });
            bump();
          },
          onMeta: (src, steps) => {
            const key = activeKey;
            const session = sessionsRef.current.get(key);
            if (!session) {
              return;
            }
            sessionsRef.current.set(key, {
              ...session,
              messages: patchAssistantMessage(session.messages, assistantId, {
                sources: src,
                reasoning: steps,
              }),
            });
            bump();
          },
          onError: (detail) => {
            showToast(detail);
          },
        });

        if (res.threadId && activeKey.startsWith('pending:')) {
          migratePendingToThread(patientId, res.threadId);
          activeKey = res.threadId;
        } else if (res.threadId) {
          activeKey = res.threadId;
        }

        const session = sessionsRef.current.get(activeKey);
        if (!session) {
          return res.threadId ?? threadId;
        }

        const finalMessages = patchAssistantMessage(session.messages, assistantId, {
          text: res.text,
          streaming: false,
          sources: res.sources,
          reasoning: res.reasoning,
          ...(res.guardrailStatus ? { guardrailStatus: res.guardrailStatus } : {}),
          ...(res.messageId ? { persistedMessageId: res.messageId } : {}),
        });

        setSession(activeKey, {
          ...session,
          threadId: res.threadId ?? session.threadId,
          sessionKey: res.threadId ?? activeKey,
          status: 'idle',
          messages: !res.text.trim()
            ? patchAssistantMessage(finalMessages, assistantId, {
                text:
                  '__FALLBACK__O assistente não devolveu texto. Verifique o backend e o Ollama.__',
                streaming: false,
              })
            : finalMessages,
        });

        if (res.threadId) {
          refreshConversations();
        }

        return res.threadId ?? threadId;
      } catch {
        const session = sessionsRef.current.get(activeKey);
        if (session) {
          setSession(activeKey, {
            ...session,
            status: 'idle',
            messages: session.messages.filter((m) => m.id !== assistantId),
          });
        }
        return threadId;
      }
    },
    [bump, migratePendingToThread, refreshConversations, setSession, showToast],
  );

  const submitFeedback = useCallback(
    async (
      patientId: string,
      threadId: string | null,
      localMessageId: string,
      clicked: MessageFeedbackRating,
    ) => {
      const key = resolveSessionKey(patientId, threadId);
      const session = sessionsRef.current.get(key);
      const effectiveThreadId = session?.threadId ?? threadId;
      const msg = session?.messages.find((m) => m.id === localMessageId);
      if (!msg?.persistedMessageId || !effectiveThreadId) {
        return;
      }

      const previous = msg.feedbackRating;
      const nextRating = previous === clicked ? undefined : clicked;

      patchMessage(patientId, threadId, localMessageId, {
        feedbackRating: nextRating,
        feedbackSubmitting: true,
      });

      try {
        await patchAssistantMessageFeedback(
          effectiveThreadId,
          msg.persistedMessageId,
          nextRating ?? null,
        );
      } catch {
        patchMessage(patientId, threadId, localMessageId, {
          feedbackRating: previous,
        });
        showToast('Não foi possível salvar sua avaliação. Tente novamente.');
      } finally {
        patchMessage(patientId, threadId, localMessageId, {
          feedbackSubmitting: false,
        });
      }
    },
    [patchMessage, showToast],
  );

  const clearPendingSession = useCallback(
    (patientId: string) => {
      const pk = pendingSessionKey(patientId);
      const pending = sessionsRef.current.get(pk);
      if (pending?.status === 'generating') {
        return;
      }
      sessionsRef.current.delete(pk);
      bump();
    },
    [bump],
  );

  const value = useMemo(
    () => ({
      version,
      getSession,
      ensureSessionLoaded,
      sendMessage,
      isThreadGenerating,
      getOptimisticSidebarEntries,
      patchMessage,
      updateMessages,
      submitFeedback,
      clearPendingSession,
    }),
    [
      version,
      getSession,
      ensureSessionLoaded,
      sendMessage,
      isThreadGenerating,
      getOptimisticSidebarEntries,
      patchMessage,
      updateMessages,
      submitFeedback,
      clearPendingSession,
    ],
  );

  return (
    <ChatSessionContext.Provider value={value}>
      {children}
    </ChatSessionContext.Provider>
  );
}

export function useChatSession(): ChatSessionContextValue {
  const ctx = useContext(ChatSessionContext);
  if (!ctx) {
    throw new Error('useChatSession deve ser usado dentro de ChatSessionProvider');
  }
  return ctx;
}
