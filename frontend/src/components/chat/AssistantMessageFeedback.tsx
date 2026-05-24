import type { MessageFeedbackRating } from '@/types/domain';

const TOOLTIP_BASE =
  'Avaliar esta resposta — seu feedback ajuda a melhorar o assistente';
const TOOLTIP_RATED = `${TOOLTIP_BASE}. Clique novamente no mesmo ícone para remover a avaliação.`;

/** Mesmas classes dos toggles Fontes / Raciocínio em AssistantMessageMeta. */
function metaToolbarButtonClass(active: boolean): string {
  const base =
    'inline-flex items-center rounded-md border-0 px-2 py-1 text-xs font-medium text-teal-800 transition-colors';
  if (active) {
    return `${base} bg-slate-300/90`;
  }
  return `${base} bg-transparent hover:bg-slate-200/80`;
}

/** Visibilidade: sem voto só no hover; com voto só o selecionado fora do hover. */
function feedbackVisibilityClass(
  hasRating: boolean,
  rating: MessageFeedbackRating | undefined,
  kind: MessageFeedbackRating,
): string {
  if (!hasRating) {
    return 'opacity-0 group-hover:opacity-100';
  }
  if (rating === kind) {
    return '';
  }
  return 'hidden group-hover:inline-flex';
}

export interface AssistantMessageFeedbackProps {
  rating?: MessageFeedbackRating;
  disabled?: boolean;
  onSelect: (rating: MessageFeedbackRating) => void;
}

/** Botões 👍/👎 para feedback (estilo alinhado a Fontes / Raciocínio). */
export function AssistantMessageFeedback({
  rating,
  disabled = false,
  onSelect,
}: AssistantMessageFeedbackProps) {
  const hasRating = rating != null;
  const tooltip = hasRating ? TOOLTIP_RATED : TOOLTIP_BASE;

  return (
    <div
      className="ml-auto flex shrink-0 items-center justify-end gap-1"
      role="group"
      aria-label="Avaliação da resposta do assistente"
    >
      <button
        type="button"
        disabled={disabled}
        title={tooltip}
        aria-label="Avaliar positivamente"
        aria-pressed={rating === 'positive'}
        onClick={() => onSelect('positive')}
        className={`${metaToolbarButtonClass(rating === 'positive')} ${feedbackVisibilityClass(hasRating, rating, 'positive')}`}
      >
        <span aria-hidden>👍</span>
      </button>
      <button
        type="button"
        disabled={disabled}
        title={tooltip}
        aria-label="Avaliar negativamente"
        aria-pressed={rating === 'negative'}
        onClick={() => onSelect('negative')}
        className={`${metaToolbarButtonClass(rating === 'negative')} ${feedbackVisibilityClass(hasRating, rating, 'negative')}`}
      >
        <span aria-hidden>👎</span>
      </button>
    </div>
  );
}
