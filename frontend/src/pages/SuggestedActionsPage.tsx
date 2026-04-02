export function SuggestedActionsPage() {
  return (
    <div>
      <h2 className="text-xl font-semibold text-slate-900">Ações sugeridas</h2>

      <p className="mt-2 text-slate-600">Propósito: mostrar a saída estruturada do assistente</p>
      <p className="mt-2 text-slate-600">Layout em duas colunas. À esquerda, o resumo do caso gerado pelo agente (hipótese diagnóstica, contexto clínico). À direita, a conduta sugerida em formato de checklist interativo: prescrições, exames a solicitar, observações de enfermagem, revisão em X horas. Cada item tem um botão "Aceitar" ou "Modificar" — mesmo que mock, comunica que o médico tem controle final. No rodapé, a referência ao protocolo consultado (ex: PCDT Sepse — MS 2019).</p>
      <p className="mt-2 text-slate-600"><b>O que demonstra:</b> que a IA sugere, mas o médico decide — fundamental para credibilidade clínica e ética.</p>
    </div>
  );
}
