export function DashboardPage() {
  return (
    <div>
      <h2 className="text-xl font-semibold text-slate-900">Dashboard do Paciente</h2>
      <p className="mt-2 text-slate-600">Propósito: ponto de entrada, visão geral do caso</p>
      <p className="mt-2 text-slate-600">Exibe um card de identificação (nome fictício, idade, CID principal, internação), seguido de três colunas: sinais vitais recentes em métricas simples (pressão, temperatura, saturação), lista de medicamentos em uso, e alertas ativos destacados em vermelho/amarelo. Abaixo, uma linha do tempo horizontal com os eventos do paciente (admissão, exames, intercorrências). Tudo mock, mas organizado como um prontuário real.</p>
      <p className="mt-2 text-slate-600"><b>O que demonstra:</b> que o sistema consolida dados de múltiplas fontes em uma visão única.</p>
    </div>
  );
}
