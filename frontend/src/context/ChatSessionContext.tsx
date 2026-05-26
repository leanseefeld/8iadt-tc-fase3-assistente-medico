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
  postRegenerateAssistantMessage,
} from '@/api/clinicalApi';
import { useConversationRefresh } from '@/context/ConversationRefreshContext';
import { useToast } from '@/context/ToastContext';
import type { ConversationMessageDto, MessageFeedbackRating } from '@/types/domain';
import type { ChatMessage, ChatSession, OptimisticConversationEntry } from '@/types/chatSession';
import {
  draftSessionKey,
  mergeStreamMeta,
  resolveSessionKey,
  sessionHasInFlightWork,
  truncatePreview,
} from '@/types/chatSession';

interface ChatSessionContextValue {
  version: number;
  getSession: (
    patientId: string,
    threadId: string | null,
    draftId?: string | null,
  ) => ChatSession;
  ensureSessionLoaded: (patientId: string, threadId: string | null) => Promise<void>;
  sendMessage: (
    patientId: string,
    threadId: string | null,
    draftId: string | null,
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
    draftId: string | null,
    messageId: string,
    patch: Partial<ChatMessage>,
  ) => void;
  updateMessages: (
    patientId: string,
    threadId: string | null,
    draftId: string | null,
    updater: (messages: ChatMessage[]) => ChatMessage[],
  ) => void;
  submitFeedback: (
    patientId: string,
    threadId: string | null,
    draftId: string | null,
    localMessageId: string,
    clicked: MessageFeedbackRating,
  ) => Promise<void>;
  regenerateMessage: (
    patientId: string,
    threadId: string | null,
    draftId: string | null,
    localMessageId: string,
  ) => Promise<void>;
  clearDraftSession: (patientId: string, draftId: string) => void;
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

function emptySession(
  patientId: string,
  threadId: string | null,
  draftId?: string | null,
): ChatSession {
  const sessionKey = resolveSessionKey(patientId, threadId, draftId);
  return {
    sessionKey,
    threadId,
    draftId: threadId ? null : (draftId ?? null),
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

function sessionKeyIsDraft(key: string): boolean {
  return key.startsWith('draft:');
}

function draftIdFromSessionKey(key: string): string | null {
  if (!sessionKeyIsDraft(key)) {
    return null;
  }
  return key.slice('draft:'.length);
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
    (
      patientId: string,
      threadId: string | null,
      draftId?: string | null,
    ): ChatSession => {
      if (threadId) {
        return sessionsRef.current.get(threadId) ?? emptySession(patientId, threadId);
      }
      if (draftId) {
        const key = draftSessionKey(draftId);
        return sessionsRef.current.get(key) ?? emptySession(patientId, null, draftId);
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
      const draftId = draftIdFromSessionKey(key);
      const current =
        sessionsRef.current.get(key) ??
        emptySession('', sessionKeyIsDraft(key) ? null : key, draftId);
      const next = updater(current);
      sessionsRef.current.set(key, next);
      bump();
    },
    [bump],
  );

  const migrateDraftToThread = useCallback(
    (draftId: string, threadId: string) => {
      const dk = draftSessionKey(draftId);
      const draft = sessionsRef.current.get(dk);
      if (!draft) {
        return;
      }
      sessionsRef.current.set(threadId, {
        ...draft,
        sessionKey: threadId,
        threadId,
        draftId: null,
      });
      sessionsRef.current.delete(dk);
      bump();
    },
    [bump],
  );

  const isThreadGenerating = useCallback((threadId: string): boolean => {
    return sessionHasInFlightWork(sessionsRef.current.get(threadId));
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

      for (const session of sessionsRef.current.values()) {
        if (session.patientId !== patientId) {
          continue;
        }

        const firstUser = session.messages.find((m) => m.role === 'user');
        if (!firstUser?.text.trim()) {
          continue;
        }

        if (session.threadId && !apiConversationIds.has(session.threadId)) {
          pushEntry({
            id: session.threadId,
            preview: truncatePreview(firstUser.text),
            generating: sessionHasInFlightWork(session),
            isPendingDraft: false,
          });
          continue;
        }

        const draftId = session.draftId ?? draftIdFromSessionKey(session.sessionKey);
        if (draftId && sessionKeyIsDraft(session.sessionKey)) {
          pushEntry({
            id: draftId,
            preview: truncatePreview(firstUser.text),
            generating: sessionHasInFlightWork(session),
            isPendingDraft: true,
            draftId,
          });
        }
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
      if (sessionHasInFlightWork(existing)) {
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
      draftId: string | null,
      messageId: string,
      patch: Partial<ChatMessage>,
    ) => {
      const key = resolveSessionKey(patientId, threadId, draftId);
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
      draftId: string | null,
      updater: (messages: ChatMessage[]) => ChatMessage[],
    ) => {
      const key = resolveSessionKey(patientId, threadId, draftId);
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
      draftId: string | null,
      text: string,
    ): Promise<string | null> => {
      const trimmed = text.trim();
      if (!trimmed) {
        return threadId;
      }
      if (!threadId && !draftId) {
        return null;
      }

      let activeKey = resolveSessionKey(patientId, threadId, draftId);
      const existing =
        sessionsRef.current.get(activeKey) ??
        emptySession(patientId, threadId, draftId);
      const assistantId = `a-${Date.now()}`;

      setSession(activeKey, {
        ...existing,
        patientId,
        threadId,
        draftId: threadId ? null : draftId,
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

        if (res.threadId && sessionKeyIsDraft(activeKey)) {
          const resolvedDraftId = draftIdFromSessionKey(activeKey);
          if (resolvedDraftId) {
            migrateDraftToThread(resolvedDraftId, res.threadId);
            activeKey = res.threadId;
          }
        } else if (res.threadId) {
          activeKey = res.threadId;
        }

        const session = sessionsRef.current.get(activeKey);
        if (!session) {
          return res.threadId ?? threadId;
        }

        const prevAssistant = session.messages.find((m) => m.id === assistantId);
        const finalMessages = patchAssistantMessage(session.messages, assistantId, {
          text: res.text,
          streaming: false,
          sources: mergeStreamMeta(res.sources, prevAssistant?.sources),
          reasoning: mergeStreamMeta(res.reasoning, prevAssistant?.reasoning),
          ...(res.guardrailStatus ? { guardrailStatus: res.guardrailStatus } : {}),
          ...(res.messageId ? { persistedMessageId: res.messageId } : {}),
        });

        setSession(activeKey, {
          ...session,
          threadId: res.threadId ?? session.threadId,
          draftId: null,
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
    [bump, migrateDraftToThread, refreshConversations, setSession, showToast],
  );

  const submitFeedback = useCallback(
    async (
      patientId: string,
      threadId: string | null,
      draftId: string | null,
      localMessageId: string,
      clicked: MessageFeedbackRating,
    ) => {
      const key = resolveSessionKey(patientId, threadId, draftId);
      const session = sessionsRef.current.get(key);
      const effectiveThreadId = session?.threadId ?? threadId;
      const msg = session?.messages.find((m) => m.id === localMessageId);
      if (!msg?.persistedMessageId || !effectiveThreadId) {
        return;
      }

      const previous = msg.feedbackRating;
      const nextRating = previous === clicked ? undefined : clicked;

      patchMessage(patientId, threadId, draftId, localMessageId, {
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
        patchMessage(patientId, threadId, draftId, localMessageId, {
          feedbackRating: previous,
        });
        showToast('Não foi possível salvar sua avaliação. Tente novamente.');
      } finally {
        patchMessage(patientId, threadId, draftId, localMessageId, {
          feedbackSubmitting: false,
        });
      }
    },
    [patchMessage, showToast],
  );

  const regenerateMessage = useCallback(
    async (
      patientId: string,
      threadId: string | null,
      draftId: string | null,
      localMessageId: string,
    ) => {
      const key = resolveSessionKey(patientId, threadId, draftId);
      const session = sessionsRef.current.get(key);
      const effectiveThreadId = session?.threadId ?? threadId;
      const msg = session?.messages.find((m) => m.id === localMessageId);
      if (!msg?.persistedMessageId || !effectiveThreadId) {
        return;
      }
      if (msg.regenerating || session?.status === 'generating') {
        return;
      }
      if (session?.messages.some((m) => m.regenerating)) {
        return;
      }

      const previousText = msg.text;
      const previousSources = msg.sources;
      const previousReasoning = msg.reasoning;
      const previousPersistedId = msg.persistedMessageId;
      const previousFeedback = msg.feedbackRating;

      patchMessage(patientId, threadId, draftId, localMessageId, {
        regenerating: true,
        streaming: true,
        text: '',
        sources: [],
        reasoning: [],
        expandedPanel: null,
        feedbackRating: undefined,
      });

      try {
        const res = await postRegenerateAssistantMessage(
          effectiveThreadId,
          previousPersistedId,
          {
            onToken: (delta) => {
              const current = sessionsRef.current.get(key);
              if (!current) {
                return;
              }
              sessionsRef.current.set(key, {
                ...current,
                messages: patchAssistantMessage(current.messages, localMessageId, {
                  text:
                    (current.messages.find((m) => m.id === localMessageId)?.text ??
                      '') + delta,
                }),
              });
              bump();
            },
            onMeta: (src, steps) => {
              const current = sessionsRef.current.get(key);
              if (!current) {
                return;
              }
              sessionsRef.current.set(key, {
                ...current,
                messages: patchAssistantMessage(current.messages, localMessageId, {
                  sources: src,
                  reasoning: steps,
                }),
              });
              bump();
            },
            onError: (detail) => {
              showToast(detail);
            },
          },
        );

        const current = sessionsRef.current.get(key);
        const prevAssistant = current?.messages.find((m) => m.id === localMessageId);
        patchMessage(patientId, threadId, draftId, localMessageId, {
          text: res.text,
          streaming: false,
          regenerating: false,
          sources: mergeStreamMeta(res.sources, prevAssistant?.sources),
          reasoning: mergeStreamMeta(res.reasoning, prevAssistant?.reasoning),
          ...(res.guardrailStatus ? { guardrailStatus: res.guardrailStatus } : {}),
          ...(res.messageId ? { persistedMessageId: res.messageId } : {}),
        });
      } catch {
        patchMessage(patientId, threadId, draftId, localMessageId, {
          regenerating: false,
          streaming: false,
          text: previousText,
          sources: previousSources,
          reasoning: previousReasoning,
          persistedMessageId: previousPersistedId,
          feedbackRating: previousFeedback,
        });
        showToast('Não foi possível regenerar a resposta. Tente novamente.');
      }
    },
    [bump, patchMessage, showToast],
  );

  const clearDraftSession = useCallback(
    (patientId: string, draftId: string) => {
      const dk = draftSessionKey(draftId);
      const draft = sessionsRef.current.get(dk);
      if (!draft || draft.patientId !== patientId) {
        return;
      }
      if (sessionHasInFlightWork(draft)) {
        return;
      }
      sessionsRef.current.delete(dk);
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
      regenerateMessage,
      clearDraftSession,
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
      regenerateMessage,
      clearDraftSession,
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
