function metaToolbarButtonClass(): string {
  return 'inline-flex items-center rounded-md border-0 px-2 py-1 text-xs font-medium text-teal-800 transition-colors bg-transparent hover:bg-slate-200/80 disabled:cursor-not-allowed disabled:opacity-50';
}

export interface AssistantMessageRegenerateProps {
  disabled?: boolean;
  busy?: boolean;
  onRegenerate: () => void;
}

const TOOLTIP =
  'Gerar outra resposta para a mesma pergunta — só a última resposta pode ser refeita';

/** Botão 🔄 para regenerar a última resposta do assistente. */
export function AssistantMessageRegenerate({
  disabled = false,
  busy = false,
  onRegenerate,
}: AssistantMessageRegenerateProps) {
  const tooltip = busy
    ? 'Aguarde a geração da nova resposta terminar'
    : TOOLTIP;

  return (
    <button
      type="button"
      disabled={disabled || busy}
      title={tooltip}
      aria-label="Regenerar resposta do assistente"
      onClick={onRegenerate}
      className={`${metaToolbarButtonClass()} ${busy ? '' : 'opacity-0 group-hover:opacity-100'}`}
    >
      <span aria-hidden>{busy ? '⏳' : '🔄'}</span>
    </button>
  );
}
