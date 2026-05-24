import { Send } from 'lucide-react';
import { useEffect, useState, type FormEvent } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  patchAssistantMessageFeedback,
  postAssistantChatMock,
  quickQuestionsForCid,
} from '@/api/clinicalApi';
import {
  AssistantMessageMeta,
  assistantMessageShowsFooter,
  type ExpandedMetaPanel,
} from '@/components/chat/AssistantMessageMeta';
import { useAppSession } from '@/context/AppSessionContext';
import { useToast } from '@/context/ToastContext';
import { usePatientDetail } from '@/hooks/usePatientDetail';
import type { GuardrailStatus, MessageFeedbackRating } from '@/types/domain';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  /** True enquanto tokens SSE estão chegando (modo HTTP). */
  streaming?: boolean;
  sources?: string[];
  reasoning?: string[];
  /** Painel de meta aberto; no máximo um por mensagem. */
  expandedPanel?: ExpandedMetaPanel | null;
  guardrailStatus?: GuardrailStatus;
  /** Id da mensagem no SQLite (para PATCH de feedback). */
  persistedMessageId?: string;
  feedbackRating?: MessageFeedbackRating;
  feedbackSubmitting?: boolean;
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

export function ChatPage() {
  const { activePatientId } = useAppSession();
  const { patient } = usePatientDetail(activePatientId);
  const { showToast } = useToast();
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [assistantThreadId, setAssistantThreadId] = useState<string | null>(null);
  const [feedbackBusyMessageId, setFeedbackBusyMessageId] = useState<string | null>(
    null,
  );

  useEffect(() => {
    setMessages([]);
    setAssistantThreadId(null);
  }, [activePatientId]);

  async function handleFeedbackSelect(
    localMessageId: string,
    clicked: MessageFeedbackRating,
  ) {
    const msg = messages.find((m) => m.id === localMessageId);
    if (!msg?.persistedMessageId || !assistantThreadId) {
      return;
    }
    const previous = msg.feedbackRating;
    const nextRating = previous === clicked ? undefined : clicked;

    setMessages((m) =>
      patchAssistantMessage(m, localMessageId, {
        feedbackRating: nextRating,
        feedbackSubmitting: true,
      }),
    );
    setFeedbackBusyMessageId(localMessageId);

    try {
      await patchAssistantMessageFeedback(
        assistantThreadId,
        msg.persistedMessageId,
        nextRating ?? null,
      );
    } catch {
      setMessages((m) =>
        patchAssistantMessage(m, localMessageId, {
          feedbackRating: previous,
        }),
      );
      showToast('Não foi possível salvar sua avaliação. Tente novamente.');
    } finally {
      setFeedbackBusyMessageId(null);
      setMessages((m) =>
        patchAssistantMessage(m, localMessageId, {
          feedbackSubmitting: false,
        }),
      );
    }
  }

  function toggleMessagePanel(messageId: string, panel: ExpandedMetaPanel) {
    setMessages((m) =>
      m.map((msg) => {
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

  if (!activePatientId || !patient) {
    return (
      <p className="text-slate-600">Selecione um paciente para usar o chat.</p>
    );
  }

  const quick = quickQuestionsForCid(patient.cid.code);

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed) {
      return;
    }
    // Histórico multi-turno: servidor (threadId + checkpointer); não enviar messageHistory.
    setMessages((m) => [
      ...m,
      { id: `u-${Date.now()}`, role: 'user', text: trimmed },
    ]);
    setInput('');

    const assistantId = `a-${Date.now()}`;
    setMessages((m) => [
      ...m,
      { id: assistantId, role: 'assistant', text: '', streaming: true },
    ]);
    try {
      const res = await postAssistantChatMock(activePatientId!, trimmed, {
        threadId: assistantThreadId ?? undefined,
        onToken: (delta) => {
          setMessages((m) =>
            patchAssistantMessage(m, assistantId, {
              text: (m.find((x) => x.id === assistantId)?.text ?? '') + delta,
            }),
          );
        },
        onMeta: (src, steps) => {
          setMessages((m) =>
            patchAssistantMessage(m, assistantId, {
              sources: src,
              reasoning: steps,
            }),
          );
        },
        onError: (detail) => {
          showToast(detail);
        },
      });
      setMessages((m) =>
        patchAssistantMessage(m, assistantId, {
          text: res.text,
          streaming: false,
          sources: res.sources,
          reasoning: res.reasoning,
          ...(res.guardrailStatus
            ? { guardrailStatus: res.guardrailStatus }
            : {}),
          ...(res.messageId ? { persistedMessageId: res.messageId } : {}),
        }),
      );
      if (res.threadId) {
        setAssistantThreadId(res.threadId);
      }
      if (!res.text.trim()) {
        setMessages((m) =>
          patchAssistantMessage(m, assistantId, {
            text:
              '__FALLBACK__O assistente não devolveu texto. Verifique o backend e o Ollama.__',
            streaming: false,
          }),
        );
      }
    } catch {
      setMessages((m) => m.filter((x) => x.id !== assistantId));
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void send(input);
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      <div className="flex min-h-[420px] flex-col rounded-xl border border-[var(--color-border-subtle)] bg-white shadow-sm">
        <div className="border-b px-4 py-3">
          <h2 className="text-lg font-semibold text-slate-900">
            Chat com o assistente
          </h2>
        </div>
        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {messages.length === 0 ? (
            <p className="text-sm text-slate-500">
              Use as perguntas rápidas ou digite uma mensagem.
            </p>
          ) : null}
          {messages.map((msg) =>
            msg.text.startsWith('__FALLBACK__') ? (
              <p
                key={msg.id}
                className="text-sm italic text-slate-500"
              >
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
                  <div className="[&>p]:mb-2 [&>p:last-child]:mb-0 [&>ul]:list-disc [&>ul]:pl-4 [&>ol]:list-decimal [&>ol]:pl-4 [&>pre]:bg-slate-800 [&>pre]:text-white [&>pre]:p-2 [&>pre]:rounded [&>pre]:my-2 [&>pre]:overflow-x-auto [&>code]:bg-slate-200 [&>code]:px-1 [&>code]:rounded">
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
                      showFeedback={Boolean(msg.persistedMessageId)}
                      feedbackRating={msg.feedbackRating}
                      feedbackDisabled={
                        feedbackBusyMessageId === msg.id ||
                        Boolean(msg.feedbackSubmitting)
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
                className="rounded-full border border-teal-200 bg-teal-50 px-2 py-1 text-xs text-teal-900 hover:bg-teal-100"
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
              className="min-w-0 flex-1 rounded-lg border border-[var(--color-border-subtle)] px-3 py-2 text-sm"
            />
            <button
              type="submit"
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-teal-600 text-white hover:bg-teal-700"
              aria-label="Enviar"
            >
              <Send className="h-4 w-4" />
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
