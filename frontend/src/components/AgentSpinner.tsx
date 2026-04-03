import { useEffect, useState } from 'react';

export interface AgentSpinnerProps {
  messages: string[];
  /** Duração total em ms (referência: 1,5 s). */
  totalMs?: number;
}

export function AgentSpinner({ messages, totalMs = 1500 }: AgentSpinnerProps) {
  const [idx, setIdx] = useState(0);
  const safe = messages.length > 0 ? messages : ['Processando…'];
  const step = Math.max(400, totalMs / safe.length);

  useEffect(() => {
    const id = window.setInterval(() => {
      setIdx((i) => (i + 1) % safe.length);
    }, step);
    return () => window.clearInterval(id);
  }, [safe.length, step]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 px-4"
      role="status"
      aria-live="polite"
    >
      <div className="flex max-w-md flex-col items-center gap-4 rounded-2xl border border-[var(--color-border-subtle)] bg-white p-8 shadow-xl">
        <div
          className="h-12 w-12 animate-spin rounded-full border-4 border-teal-100 border-t-teal-600"
          aria-hidden
        />
        <p className="text-center text-sm font-medium text-slate-700">
          {safe[idx]}
        </p>
      </div>
    </div>
  );
}
