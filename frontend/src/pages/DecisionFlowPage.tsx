export function DecisionFlowPage() {
  return (
    <div>
      <h2 className="text-xl font-semibold text-slate-900">Fluxo de decisão</h2>
      <p className="mt-2 text-slate-600">Propósito: tornar o LangGraph visível e compreensível</p>

      <p className="mt-2 text-slate-600">Esta é a página mais importante para comunicar a inovação. Exibe o grafo de decisão como um diagrama de nós, usando streamlit-agraph ou uma imagem estática com st.image. Quando o médico clica em "Executar fluxo para este paciente", os nós vão acendendo em sequência (verde = concluído, amarelo = em execução, vermelho = alerta), simulando a execução real.</p>
      <p className="mt-2 text-slate-600">Abaixo do diagrama, um painel de log mostra o que cada etapa encontrou:</p>

      <ul className="mt-2 text-slate-600 list-disc list-inside">
        <li>✅ Triagem: dados completos</li>
        <li>⚠️ Exames: hemograma pendente há 48h</li>
        <li>💊 Conduta: sugerido ajuste de dose (ver detalhe)</li>
        <li>🔴 Alerta: enviado para equipe de enfermagem</li>
      </ul>

      <p className="mt-2 text-slate-600"><b>O que demonstra:</b> o conceito de orquestração multi-etapa de forma visual e imediata.</p>
    </div>
  );
}
