import { AssistantMessageFeedback } from '@/components/chat/AssistantMessageFeedback';
import { AssistantMessageRegenerate } from '@/components/chat/AssistantMessageRegenerate';
import type { MessageFeedbackRating } from '@/types/domain';

export type ExpandedMetaPanel = 'sources' | 'reasoning';

export interface AssistantMessageMetaProps {
  messageId: string;
  sources: string[];
  reasoning: string[];
  expandedPanel: ExpandedMetaPanel | null;
  onTogglePanel: (panel: ExpandedMetaPanel) => void;
  /** Exibe 👍/👎 à direita quando há id persistido e conversa ativa. */
  showFeedback?: boolean;
  feedbackRating?: MessageFeedbackRating;
  feedbackDisabled?: boolean;
  onFeedbackSelect?: (rating: MessageFeedbackRating) => void;
  /** Exibe 🔄 antes do feedback na última resposta persistida. */
  showRegenerate?: boolean;
  regenerateDisabled?: boolean;
  regenerateBusy?: boolean;
  onRegenerate?: () => void;
}

function metaToggleButtonClass(active: boolean): string {
  const base =
    'rounded-md border-0 px-2 py-1 text-xs font-medium text-teal-800 transition-colors';
  if (active) {
    return `${base} bg-slate-300/90`;
  }
  return `${base} bg-transparent hover:bg-slate-200/80`;
}

/** Rodapé: fontes/raciocínio à esquerda; feedback 👍/👎 à direita. */
export function AssistantMessageMeta({
  messageId,
  sources,
  reasoning,
  expandedPanel,
  onTogglePanel,
  showFeedback = false,
  feedbackRating,
  feedbackDisabled = false,
  onFeedbackSelect,
  showRegenerate = false,
  regenerateDisabled = false,
  regenerateBusy = false,
  onRegenerate,
}: AssistantMessageMetaProps) {
  const sourcesPanelId = `${messageId}-sources-panel`;
  const reasoningPanelId = `${messageId}-reasoning-panel`;
  const sourcesActive = expandedPanel === 'sources';
  const reasoningActive = expandedPanel === 'reasoning';

  return (
    <div className="mt-2 flex w-full flex-col items-start gap-1 border-t border-slate-200/90 pt-2">
      <div className="flex w-full items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap justify-start gap-1">
          {sources.length > 0 ? (
            <button
              type="button"
              onClick={() => onTogglePanel('sources')}
              aria-expanded={sourcesActive}
              aria-controls={sourcesPanelId}
              aria-pressed={sourcesActive}
              className={metaToggleButtonClass(sourcesActive)}
            >
              <span aria-hidden>🔍</span> Fontes ({sources.length})
            </button>
          ) : null}
          {reasoning.length > 0 ? (
            <button
              type="button"
              onClick={() => onTogglePanel('reasoning')}
              aria-expanded={reasoningActive}
              aria-controls={reasoningPanelId}
              aria-pressed={reasoningActive}
              className={metaToggleButtonClass(reasoningActive)}
            >
              <span aria-hidden>🧠</span> Raciocínio ({reasoning.length})
            </button>
          ) : null}
        </div>
        {(showRegenerate && onRegenerate) || (showFeedback && onFeedbackSelect) ? (
          <div className="ml-auto flex shrink-0 items-center justify-end gap-1">
            {showRegenerate && onRegenerate ? (
              <AssistantMessageRegenerate
                disabled={regenerateDisabled}
                busy={regenerateBusy}
                onRegenerate={onRegenerate}
              />
            ) : null}
            {showFeedback && onFeedbackSelect ? (
              <AssistantMessageFeedback
                rating={feedbackRating}
                disabled={feedbackDisabled}
                onSelect={onFeedbackSelect}
              />
            ) : null}
          </div>
        ) : null}
      </div>
      {sourcesActive && sources.length > 0 ? (
        <ul
          id={sourcesPanelId}
          className="max-h-40 w-full list-none overflow-y-auto rounded-lg border border-[var(--color-border-subtle)] bg-white px-3 py-2 text-left text-xs text-slate-700"
        >
          {sources.map((s, i) => (
            <li key={`${s}-${i}`} className="mb-1 last:mb-0">
              {s}
            </li>
          ))}
        </ul>
      ) : null}
      {reasoningActive && reasoning.length > 0 ? (
        <ul
          id={reasoningPanelId}
          className="max-h-40 w-full list-none overflow-y-auto rounded-lg border border-[var(--color-border-subtle)] bg-white px-3 py-2 text-left text-xs text-slate-600"
        >
          {reasoning.map((step, i) => (
            <li key={i} className="mb-1 last:mb-0">
              {step}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** Indica se a mensagem tem meta (fontes/raciocínio) para exibir após o streaming. */
export function assistantMessageHasMeta(msg: {
  sources?: string[];
  reasoning?: string[];
}): boolean {
  return (
    (msg.sources?.length ?? 0) > 0 || (msg.reasoning?.length ?? 0) > 0
  );
}

/** Exibe a barra de rodapé (meta e/ou feedback). */
export function assistantMessageShowsFooter(msg: {
  sources?: string[];
  reasoning?: string[];
  persistedMessageId?: string;
}): boolean {
  return (
    assistantMessageHasMeta(msg) || Boolean(msg.persistedMessageId?.trim())
  );
}
