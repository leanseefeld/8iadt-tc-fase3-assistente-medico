import { Archive, Loader2, MessageSquarePlus } from 'lucide-react';
import { useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { NavLink, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { archiveAssistantConversation } from '@/api/clinicalApi';
import { useAppSession } from '@/context/AppSessionContext';
import { useChatSession } from '@/context/ChatSessionContext';
import { useConversationRefresh } from '@/context/ConversationRefreshContext';
import { useToast } from '@/context/ToastContext';
import { usePatientConversations } from '@/hooks/usePatientConversations';
import type { ConversationSummary } from '@/types/domain';
import type { OptimisticConversationEntry } from '@/types/chatSession';
import { formatLocalDateTime } from '@/utils/formatDateTime';

type SidebarConversation =
  | (ConversationSummary & { isOptimistic: false })
  | (OptimisticConversationEntry & { isOptimistic: true });

function conversationLabel(preview: string | null | undefined): string {
  if (preview?.trim()) {
    return preview.trim();
  }
  return 'Conversa sem título';
}

export function ConversationSidebarSection() {
  const { activePatientId } = useAppSession();
  const { conversations, loading, error } = usePatientConversations(activePatientId);
  const { refreshConversations } = useConversationRefresh();
  const { isThreadGenerating, getOptimisticSidebarEntries, version } =
    useChatSession();
  void version;
  const { showToast } = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const activeThreadId = searchParams.get('thread');

  const [archiveTarget, setArchiveTarget] = useState<ConversationSummary | null>(
    null,
  );
  const [archiveBusy, setArchiveBusy] = useState(false);

  const sidebarItems = useMemo((): SidebarConversation[] => {
    if (!activePatientId) {
      return [];
    }
    const apiIds = new Set(conversations.map((c) => c.id));
    const optimistic = getOptimisticSidebarEntries(activePatientId, apiIds).map(
      (entry) => ({ ...entry, isOptimistic: true as const }),
    );
    const persisted = conversations.map((entry) => ({
      ...entry,
      isOptimistic: false as const,
    }));
    return [...optimistic, ...persisted];
  }, [
    activePatientId,
    conversations,
    getOptimisticSidebarEntries,
    version,
  ]);

  function startNewConversation() {
    navigate('/chat');
  }

  async function confirmArchive() {
    if (!archiveTarget) {
      return;
    }
    setArchiveBusy(true);
    try {
      await archiveAssistantConversation(archiveTarget.id);
      showToast('Conversa arquivada.');
      if (activeThreadId === archiveTarget.id) {
        navigate('/chat');
      }
      refreshConversations();
    } catch {
      showToast('Não foi possível arquivar a conversa.');
    } finally {
      setArchiveBusy(false);
      setArchiveTarget(null);
    }
  }

  const onChatRoute = location.pathname === '/chat';

  return (
    <div className="flex flex-col border-t border-[var(--color-border-subtle)] px-2 py-3">
      <button
        type="button"
        onClick={startNewConversation}
        disabled={!activePatientId}
        className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-sm font-medium text-teal-800 transition-colors hover:bg-teal-50 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <MessageSquarePlus className="h-4 w-4 shrink-0" aria-hidden />
        Nova conversa
      </button>

      <p className="mt-3 px-3 text-xs font-medium uppercase tracking-wide text-slate-500">
        Conversas
      </p>

      {!activePatientId ? (
        <p className="mt-2 px-3 text-xs text-slate-500">
          Selecione um paciente.
        </p>
      ) : loading ? (
        <p className="mt-2 px-3 text-xs text-slate-500">Carregando…</p>
      ) : error ? (
        <p className="mt-2 px-3 text-xs text-red-700">{error}</p>
      ) : sidebarItems.length === 0 ? (
        <p className="mt-2 px-3 text-xs text-slate-500">Nenhuma conversa.</p>
      ) : (
        <ul className="mt-1 flex flex-col gap-0.5" aria-label="Conversas salvas">
          {sidebarItems.map((conv) => {
            const isActive = conv.isOptimistic
              ? conv.isPendingDraft
                ? onChatRoute && !activeThreadId
                : onChatRoute && activeThreadId === conv.id
              : onChatRoute && activeThreadId === conv.id;
            const generating = conv.isOptimistic
              ? conv.generating
              : isThreadGenerating(conv.id);
            const label = conversationLabel(conv.preview);
            const linkTo = conv.isOptimistic
              ? conv.isPendingDraft
                ? '/chat'
                : `/chat?thread=${encodeURIComponent(conv.id)}`
              : `/chat?thread=${encodeURIComponent(conv.id)}`;

            return (
              <li key={conv.id} className="group relative">
                <NavLink
                  to={linkTo}
                  title={label}
                  className={() =>
                    [
                      'block rounded-lg px-3 py-2 pr-9 text-left text-sm transition-colors',
                      isActive
                        ? 'bg-teal-600 text-white'
                        : 'text-slate-700 hover:bg-slate-100',
                      generating && !isActive ? 'ring-1 ring-amber-300' : '',
                    ].join(' ')
                  }
                >
                  <span className="line-clamp-2 font-medium leading-snug">
                    {label}
                  </span>
                  <span
                    className={`mt-0.5 flex min-h-[14px] items-center text-[10px] ${
                      isActive ? 'text-teal-100' : 'text-slate-500'
                    }`}
                  >
                    {generating ? (
                      <Loader2
                        className={`h-3 w-3 animate-spin shrink-0 ${
                          isActive ? 'text-teal-100' : 'text-amber-600'
                        }`}
                        aria-label="Gerando resposta"
                      />
                    ) : conv.isOptimistic ? null : (
                      formatLocalDateTime(conv.updatedAt)
                    )}
                  </span>
                </NavLink>
                {!conv.isOptimistic ? (
                  <button
                    type="button"
                    aria-label="Arquivar conversa"
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setArchiveTarget(conv);
                    }}
                    className={`absolute right-1 top-1/2 -translate-y-1/2 rounded p-1 opacity-0 transition-opacity group-hover:opacity-100 focus:opacity-100 ${
                      isActive
                        ? 'text-teal-100 hover:bg-teal-700'
                        : 'text-slate-500 hover:bg-slate-200'
                    }`}
                  >
                    <Archive className="h-3.5 w-3.5" aria-hidden />
                  </button>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}

      {archiveTarget
        ? createPortal(
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
              <div
                role="dialog"
                aria-modal="true"
                aria-labelledby="archive-conversation-title"
                className="w-full max-w-sm rounded-xl border bg-white p-5 shadow-xl"
              >
                <h4
                  id="archive-conversation-title"
                  className="font-semibold text-slate-900"
                >
                  Arquivar conversa?
                </h4>
                <p className="mt-2 text-sm text-slate-600">
                  A conversa ficará inacessível, mas permanecerá registrada para
                  auditoria.
                </p>
                <p className="mt-2 line-clamp-2 text-xs text-slate-500">
                  {conversationLabel(archiveTarget.preview)}
                </p>
                <div className="mt-4 flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setArchiveTarget(null)}
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
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
