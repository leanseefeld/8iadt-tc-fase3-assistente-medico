import { Link } from 'react-router-dom';
import { useCallback, useEffect, useRef, useState } from 'react';
import { postAssistantDecisionFlowMock } from '@/api/clinicalApi';
import { useAppSession } from '@/context/AppSessionContext';
import { usePatientDetail } from '@/hooks/usePatientDetail';

type NodeState = 'idle' | 'running' | 'done' | 'alert';

const MAIN_NODES = [
  { id: 'triage', label: 'Triagem' },
  { id: 'protocol', label: 'Consulta Protocolo' },
  { id: 'exams', label: 'Checar Exames' },
  { id: 'suggest', label: 'Sugerir Ações' },
  { id: 'emit', label: 'Emitir Alertas' },
] as const;

function nodeClass(state: NodeState): string {
  const base =
    'flex min-w-[5.5rem] flex-col items-center rounded-lg border-2 px-2 py-3 text-center text-xs font-medium transition-all';
  if (state === 'idle') {
    return `${base} border-slate-200 bg-slate-50 text-slate-500`;
  }
  if (state === 'running') {
    return `${base} animate-pulse border-amber-400 bg-amber-50 text-amber-900`;
  }
  if (state === 'alert') {
    return `${base} border-red-500 bg-red-50 text-red-900`;
  }
  return `${base} border-emerald-500 bg-emerald-50 text-emerald-900`;
}

export function DecisionFlowPage() {
  const {
    activePatientId,
    pendingFlowReview,
    setPendingFlowReview,
  } = useAppSession();
  const { patient } = usePatientDetail(activePatientId);

  const [nodeStates, setNodeStates] = useState<Record<string, NodeState>>(() =>
    Object.fromEntries(
      [...MAIN_NODES.map((n) => n.id), 'immediate'].map((id) => [id, 'idle']),
    ),
  );
  const [immediateVisible, setImmediateVisible] = useState(false);
  const [logLines, setLogLines] = useState<string[]>([]);
  const [ranOnce, setRanOnce] = useState(false);
  const [runningFlow, setRunningFlow] = useState(false);
  const timersRef = useRef<number[]>([]);

  const clearTimers = useCallback(() => {
    timersRef.current.forEach((id) => window.clearTimeout(id));
    timersRef.current = [];
  }, []);

  useEffect(() => () => clearTimers(), [clearTimers]);

  async function runFlow() {
    if (!activePatientId) {
      return;
    }
    clearTimers();
    setRunningFlow(true);
    setLogLines([]);
    setNodeStates(
      Object.fromEntries(
        [...MAIN_NODES.map((n) => n.id), 'immediate'].map((id) => [id, 'idle']),
      ),
    );
    setImmediateVisible(false);

    const res = await postAssistantDecisionFlowMock(activePatientId);
    setPendingFlowReview(false);

    let delayMs = 0;
    const step = 200;

    MAIN_NODES.forEach((n, i) => {
      const tRun = window.setTimeout(() => {
        setNodeStates((s) => ({ ...s, [n.id]: 'running' }));
      }, delayMs + i * step);
      timersRef.current.push(tRun);
      const tDone = window.setTimeout(() => {
        setNodeStates((s) => ({ ...s, [n.id]: 'done' }));
      }, delayMs + i * step + step);
      timersRef.current.push(tDone);
    });

    const baseEnd = MAIN_NODES.length * step * 2;
    if (res.meta.sepsisCritical) {
      const tVis = window.setTimeout(() => {
        setImmediateVisible(true);
        setNodeStates((s) => ({ ...s, immediate: 'alert' }));
      }, baseEnd);
      timersRef.current.push(tVis);
    }

    res.lines.forEach((line, i) => {
      const t = window.setTimeout(() => {
        setLogLines((prev) => [...prev, line]);
      }, i * 200);
      timersRef.current.push(t);
    });

    const tEnd = window.setTimeout(() => {
      setRunningFlow(false);
      setRanOnce(true);
    }, res.lines.length * 200 + 300);
    timersRef.current.push(tEnd);
  }

  if (!activePatientId || !patient) {
    return (
      <p className="text-slate-600">
        Selecione um paciente admitido para ver o fluxo de decisão.
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-900">
          Fluxo de decisão
        </h2>
        <p className="mt-1 text-sm text-slate-600">
          Orquestração multi-etapa do assistente (demonstração visual).
        </p>
      </div>

      {pendingFlowReview ? (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950">
          CID atualizado para {patient.cid.code}. Clique em &quot;Executar
          Fluxo&quot; para re-analisar.
        </div>
      ) : null}

      <div className="overflow-x-auto rounded-xl border border-[var(--color-border-subtle)] bg-white p-6">
        <div className="flex min-w-max items-center gap-2">
          {MAIN_NODES.map((n, i) => (
            <div key={n.id} className="flex items-center gap-2">
              <div className={nodeClass(nodeStates[n.id] ?? 'idle')}>
                <span>{n.label}</span>
              </div>
              {i < MAIN_NODES.length - 1 ? (
                <span className="text-slate-400" aria-hidden>
                  →
                </span>
              ) : null}
            </div>
          ))}
        </div>
        {immediateVisible ? (
          <div className="mt-6 flex justify-center">
            <div className={nodeClass(nodeStates.immediate ?? 'idle')}>
              <span className="text-base" aria-hidden>
                🔔
              </span>
              <span>Alerta Imediato</span>
            </div>
          </div>
        ) : null}
      </div>

      <div className="flex justify-center">
        <button
          type="button"
          disabled={runningFlow}
          onClick={() => void runFlow()}
          className={`rounded-lg px-6 py-2.5 text-sm font-semibold ${
            ranOnce
              ? 'border-2 border-teal-600 text-teal-800 hover:bg-teal-50'
              : 'bg-teal-600 text-white hover:bg-teal-700'
          } disabled:opacity-50`}
        >
          {ranOnce ? 'Re-executar Fluxo' : 'Executar Fluxo'}
        </button>
      </div>

      <div className="rounded-xl border border-[var(--color-border-subtle)] bg-slate-50/80 p-4">
        <h3 className="text-sm font-semibold text-slate-800">
          Log de execução
        </h3>
        <ul className="mt-3 space-y-1 font-mono text-xs text-slate-700">
          {logLines.map((line, i) => (
            <li key={`${i}-${line.slice(0, 12)}`}>{line}</li>
          ))}
        </ul>
      </div>

      <p className="text-center text-sm">
        <Link to="/suggested-actions" className="font-medium text-teal-700 underline">
          Ver ações sugeridas →
        </Link>
      </p>
    </div>
  );
}
