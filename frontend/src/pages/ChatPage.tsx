import { Send } from 'lucide-react';
import { useEffect, useState, type FormEvent } from 'react';
import {
  postAssistantChatMock,
  quickQuestionsForCid,
} from '@/api/clinicalApi';
import { useAppSession } from '@/context/AppSessionContext';
import { usePatientDetail } from '@/hooks/usePatientDetail';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
}

export function ChatPage() {
  const { activePatientId } = useAppSession();
  const { patient } = usePatientDetail(activePatientId);
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sources, setSources] = useState<string[]>([]);
  const [reasoning, setReasoning] = useState<string[]>([]);
  const [reasoningOpen, setReasoningOpen] = useState(true);

  useEffect(() => {
    setMessages([]);
    setSources([]);
    setReasoning([]);
  }, [activePatientId]);

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
    setMessages((m) => [
      ...m,
      { id: `u-${Date.now()}`, role: 'user', text: trimmed },
    ]);
    setInput('');
    const res = await postAssistantChatMock(activePatientId!, trimmed);
    setSources(res.sources);
    setReasoning(res.reasoning);
    if (!res.text.trim()) {
      setMessages((m) => [
        ...m,
        {
          id: `a-${Date.now()}`,
          role: 'assistant',
          text:
            '__FALLBACK__Esta pergunta requer consulta ao backend. Em modo demo, apenas perguntas pré-definidas têm resposta simulada.__',
        },
      ]);
      return;
    }
    setMessages((m) => [
      ...m,
      { id: `a-${Date.now()}`, role: 'assistant', text: res.text },
    ]);
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void send(input);
  }

  return (
    <div className="flex flex-col gap-4 lg:flex-row">
      <div className="flex min-h-[420px] flex-[2] flex-col rounded-xl border border-[var(--color-border-subtle)] bg-white shadow-sm">
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
                className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[85%] rounded-2xl px-4 py-2 text-sm ${
                    msg.role === 'user'
                      ? 'bg-sky-600 text-white'
                      : 'bg-slate-100 text-slate-800'
                  }`}
                >
                  <p className="whitespace-pre-wrap">{msg.text}</p>
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

      <aside className="flex flex-1 flex-col gap-4 rounded-xl border border-[var(--color-border-subtle)] bg-white p-4 shadow-sm">
        <div>
          <h3 className="text-sm font-semibold text-slate-800">
            Fontes consultadas
          </h3>
          <ul className="mt-2 space-y-1 text-sm text-slate-700">
            {sources.length ? (
              sources.map((s) => (
                <li key={s}>📄 {s}</li>
              ))
            ) : (
              <li className="text-slate-500">Nenhuma fonte ainda</li>
            )}
          </ul>
        </div>
        <div>
          <button
            type="button"
            onClick={() => setReasoningOpen((o) => !o)}
            className="text-sm font-semibold text-teal-800"
          >
            Raciocínio do agente {reasoningOpen ? '▼' : '▶'}
          </button>
          {reasoningOpen ? (
            <ul className="mt-2 space-y-1 text-xs text-slate-600">
              {reasoning.length ? (
                reasoning.map((r, i) => <li key={i}>{r}</li>)
              ) : (
                <li>Envie uma pergunta para ver o raciocínio simulado.</li>
              )}
            </ul>
          ) : null}
        </div>
      </aside>
    </div>
  );
}
