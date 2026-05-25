import { Archive, Send } from 'lucide-react';
import { useEffect, useState, type FormEvent } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import {
  archiveAssistantConversation,
  quickQuestionsForCid,
} from '@/api/clinicalApi';
import {
  AssistantMessageMeta,
  assistantMessageShowsFooter,
  type ExpandedMetaPanel,
} from '@/components/chat/AssistantMessageMeta';
import { useAppSession } from '@/context/AppSessionContext';
import { useChatSession } from '@/context/ChatSessionContext';
import { useConversationRefresh } from '@/context/ConversationRefreshContext';
import { useToast } from '@/context/ToastContext';
import { usePatientDetail } from '@/hooks/usePatientDetail';
import type { MessageFeedbackRating } from '@/types/domain';
import {
  messageIsInFlight,
  resolveRegenerateMessageId,
  sessionHasInFlightWork,
} from '@/types/chatSession';

export function ChatPage() {
  const { activePatientId } = useAppSession();
  const { patient } = usePatientDetail(activePatientId);
  const { showToast } = useToast();
  const { refreshConversations } = useConversationRefresh();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const threadFromUrl = searchParams.get('thread');

  const {
    version,
    getSession,
    ensureSessionLoaded,
    sendMessage,
    submitFeedback,
    regenerateMessage,
    updateMessages,
    clearPendingSession,
  } = useChatSession();

  const [input, setInput] = useState('');
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [archiveBusy, setArchiveBusy] = useState(false);
  const [feedbackBusyMessageId, setFeedbackBusyMessageId] = useState<string | null>(
    null,
  );
  const [loadError, setLoadError] = useState(false);

  // version in deps so UI re-renders when background stream updates session
  const session = activePatientId
    ? getSession(activePatientId, threadFromUrl)
    : null;
  void version;

  const messages = session?.messages ?? [];
  const assistantThreadId = session?.threadId ?? threadFromUrl;
  const loadingThread = session?.status === 'loading';
  const conversationInFlight = sessionHasInFlightWork(session ?? undefined);
  const regenerateMessageId = resolveRegenerateMessageId(session ?? undefined);

  useEffect(() => {
    if (!activePatientId) {
      return;
    }
    if (!threadFromUrl) {
      clearPendingSession(activePatientId);
      setLoadError(false);
      return;
    }

    setLoadError(false);
    let cancelled = false;

    void ensureSessionLoaded(activePatientId, threadFromUrl).catch((err: Error) => {
      if (cancelled) {
        return;
      }
      if (err.message === 'wrong_patient') {
        showToast('Esta conversa pertence a outro paciente.');
      } else {
        showToast('Não foi possível carregar a conversa.');
      }
      setLoadError(true);
      navigate('/chat', { replace: true });
    });

    return () => {
      cancelled = true;
    };
  }, [
    activePatientId,
    threadFromUrl,
    ensureSessionLoaded,
    clearPendingSession,
    navigate,
    showToast,
  ]);

  async function handleRegenerate(localMessageId: string) {
    if (!activePatientId || conversationInFlight) {
      return;
    }
    await regenerateMessage(activePatientId, threadFromUrl, localMessageId);
  }

  async function handleFeedbackSelect(
    localMessageId: string,
    clicked: MessageFeedbackRating,
  ) {
    if (!activePatientId) {
      return;
    }
    setFeedbackBusyMessageId(localMessageId);
    try {
      await submitFeedback(activePatientId, threadFromUrl, localMessageId, clicked);
    } finally {
      setFeedbackBusyMessageId(null);
    }
  }

  function toggleMessagePanel(messageId: string, panel: ExpandedMetaPanel) {
    if (!activePatientId) {
      return;
    }
    updateMessages(activePatientId, threadFromUrl, (msgs) =>
      msgs.map((msg) => {
        if (msg.id !== messageId) {
          return msg;
        }
        return {
          ...msg,
          expandedPanel: msg.expandedPanel === panel ? null : panel,
        };
      }),
    );
  }

  async function confirmArchive() {
    if (!assistantThreadId) {
      return;
    }
    setArchiveBusy(true);
    try {
      await archiveAssistantConversation(assistantThreadId);
      showToast('Conversa arquivada.');
      setArchiveOpen(false);
      refreshConversations();
      navigate('/chat', { replace: true });
    } catch {
      showToast('Não foi possível arquivar a conversa.');
    } finally {
      setArchiveBusy(false);
    }
  }

  if (!activePatientId || !patient) {
    return (
      <p className="text-slate-600">Selecione um paciente para usar o chat.</p>
    );
  }

  if (loadError) {
    return null;
  }

  const quick = quickQuestionsForCid(patient.cid.code);

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || loadingThread) {
      return;
    }
    setInput('');

  // Stream roda no context — sobrevive troca de rota/conversa.
    const newThreadId = await sendMessage(activePatientId!, threadFromUrl, trimmed);
    if (
      newThreadId &&
      !threadFromUrl &&
      location.pathname === '/chat' &&
      !searchParams.get('thread')
    ) {
      navigate(`/chat?thread=${encodeURIComponent(newThreadId)}`, { replace: true });
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void send(input);
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      <div className="flex min-h-[420px] flex-col rounded-xl border border-[var(--color-border-subtle)] bg-white shadow-sm">
        <div className="flex items-center justify-between gap-2 border-b px-4 py-3">
          <h2 className="text-lg font-semibold text-slate-900">
            Chat com o assistente
          </h2>
          {assistantThreadId ? (
            <button
              type="button"
              onClick={() => setArchiveOpen(true)}
              disabled={conversationInFlight}
              className="flex items-center gap-1 rounded-lg border border-amber-600 px-2 py-1 text-xs text-amber-900 hover:bg-amber-50 disabled:opacity-50"
            >
              <Archive className="h-3.5 w-3.5" aria-hidden />
              Arquivar
            </button>
          ) : null}
        </div>
        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {loadingThread ? (
            <p className="text-sm text-slate-500">Carregando conversa…</p>
          ) : null}
          {!loadingThread && messages.length === 0 ? (
            <p className="text-sm text-slate-500">
              Use as perguntas rápidas ou digite uma mensagem.
            </p>
          ) : null}
          {messages.map((msg) =>
            msg.text.startsWith('__FALLBACK__') ? (
              <p key={msg.id} className="text-sm italic text-slate-500">
                {msg.text.replace('__FALLBACK__', '')}
              </p>
            ) : (
              <div
                key={msg.id}
                className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'group items-start'}`}
              >
                <div
                  className={`max-w-[85%] rounded-2xl px-4 py-2 text-sm ${
                    msg.role === 'user'
                      ? 'bg-sky-600 text-white'
                      : 'bg-slate-100 text-slate-800'
                  }`}
                >
                  <div className="[&>p]:mb-2 [&>p:last-child]:mb-0 [&>ul]:list-disc [&>ul]:pl-4 [&>ol]:list-decimal [&>ol]:pl-4 [&>pre]:bg-slate-800 [&>pre]:text-white [&>pre]:p-2 [&>pre]:rounded [&>pre]:my-2 [&>pre]:overflow-x-auto [&>code]:bg-slate-200 [&>code]:px-1 [&>code]:rounded [&>hr]:my-2 [&>hr]:border-slate-300">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {msg.text}
                    </ReactMarkdown>
                    {msg.streaming ? (
                      <span
                        className="ml-0.5 inline-block h-3 w-0.5 animate-pulse bg-slate-500 align-middle"
                        aria-hidden
                      />
                    ) : null}
                  </div>
                  {msg.role === 'assistant' &&
                  !msg.streaming &&
                  assistantMessageShowsFooter(msg) ? (
                    <AssistantMessageMeta
                      messageId={msg.id}
                      sources={msg.sources ?? []}
                      reasoning={msg.reasoning ?? []}
                      expandedPanel={msg.expandedPanel ?? null}
                      onTogglePanel={(panel) =>
                        toggleMessagePanel(msg.id, panel)
                      }
                      showRegenerate={msg.id === regenerateMessageId}
                      regenerateBusy={Boolean(msg.regenerating)}
                      regenerateDisabled={conversationInFlight}
                      onRegenerate={() => void handleRegenerate(msg.id)}
                      showFeedback={Boolean(msg.persistedMessageId)}
                      feedbackRating={msg.feedbackRating}
                      feedbackDisabled={
                        feedbackBusyMessageId === msg.id ||
                        Boolean(msg.feedbackSubmitting) ||
                        messageIsInFlight(msg)
                      }
                      onFeedbackSelect={(rating) =>
                        void handleFeedbackSelect(msg.id, rating)
                      }
                    />
                  ) : null}
                </div>
              </div>
            ),
          )}
        </div>
        <div className="border-t p-3">
          <div className="mb-2 flex flex-wrap gap-2">
            {quick.map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => void send(q)}
                disabled={loadingThread}
                className="rounded-full border border-teal-200 bg-teal-50 px-2 py-1 text-xs text-teal-900 hover:bg-teal-100 disabled:opacity-50"
              >
                {q.length > 42 ? `${q.slice(0, 40)}…` : q}
              </button>
            ))}
          </div>
          <form onSubmit={onSubmit} className="flex gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Digite sua pergunta…"
              disabled={loadingThread || conversationInFlight}
              className="min-w-0 flex-1 rounded-lg border border-[var(--color-border-subtle)] px-3 py-2 text-sm disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={loadingThread || conversationInFlight}
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-teal-600 text-white hover:bg-teal-700 disabled:opacity-50"
              aria-label="Enviar"
            >
              <Send className="h-4 w-4" />
            </button>
          </form>
        </div>
      </div>

      {archiveOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
          <div className="w-full max-w-sm rounded-xl border bg-white p-5 shadow-xl">
            <h4 className="font-semibold text-slate-900">Arquivar conversa?</h4>
            <p className="mt-2 text-sm text-slate-600">
              A conversa ficará inacessível, mas permanecerá registrada para
              auditoria.
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setArchiveOpen(false)}
                disabled={archiveBusy}
                className="rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-slate-100"
              >
                Cancelar
              </button>
              <button
                type="button"
                disabled={archiveBusy}
                onClick={() => void confirmArchive()}
                className="rounded-lg bg-amber-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
              >
                Arquivar
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
