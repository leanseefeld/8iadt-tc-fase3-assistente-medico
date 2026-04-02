export function ChatPage() {
  return (
    <div>
      <h2 className="text-xl font-semibold text-slate-900">Chat</h2>
      <p className="mt-2 text-slate-600">Propósito: demonstrar a interação principal médico → IA</p>
      <p className="mt-2 text-slate-600">Interface de chat convencional, com balões de conversa. O painel lateral direito mostra, em tempo real, as "fontes consultadas" pelo agente (ex: PCDT Diabetes Tipo 2 — CONITEC 2023, Bula Metformina) — isso representa o RAG em ação. Abaixo das fontes, um expansível "Raciocínio do agente" que mostra os passos intermediários (pensou → buscou → concluiu).</p>
      <p className="mt-2 text-slate-600">Inclua 3–4 perguntas de exemplo como botões clicáveis (ex: "Quais exames estão pendentes?", "Há interação medicamentosa?") para facilitar a demo sem digitar.</p>
      <p className="mt-2 text-slate-600"><b>O que demonstra:</b> o RAG, o estilo de resposta clínica e a transparência do raciocínio.</p>
    </div>
  );
}
