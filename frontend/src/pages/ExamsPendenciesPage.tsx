export function ExamsPendenciesPage() {
  return (
    <div>
      <h2 className="text-xl font-semibold text-slate-900">
        Exames e pendências
      </h2>

      <p className="mt-2 text-slate-600">Propósito: simular a ferramenta checar_exames do agente</p>
      <p className="mt-2 text-slate-600">Uma tabela com os exames do paciente (nome, data de solicitação, status, resultado). Filtros simples por status (pendente / concluído / crítico). Ao clicar em um exame, abre um painel lateral com o resultado completo e a interpretação gerada pelo assistente. Um botão "Notificar médico responsável" (mock) demonstra a integração com alertas.</p>
      <p className="mt-2 text-slate-600"><b>O que demonstra:</b> que o agente pode consultar sistemas externos como HIS/LIS e agir sobre os dados.</p>
    </div>
  );
}
