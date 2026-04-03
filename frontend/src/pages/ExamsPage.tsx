import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  addAlertMock,
  patchPatientMock,
} from '@/api/clinicalApi';
import { useAppSession } from '@/context/AppSessionContext';
import { useToast } from '@/context/ToastContext';
import { usePatientDetail } from '@/hooks/usePatientDetail';
import type { Exam } from '@/types/domain';

type ExamFilter = 'all' | 'pending' | 'completed' | 'critical';

export function ExamsPage() {
  const navigate = useNavigate();
  const { showToast } = useToast();
  const { activePatientId, refreshAlertBadge } = useAppSession();
  const { patient, refetch } = usePatientDetail(activePatientId);
  const [filter, setFilter] = useState<ExamFilter>('all');
  const [selected, setSelected] = useState<Exam | null>(null);
  const [modalExam, setModalExam] = useState<Exam | null>(null);
  const [resultValue, setResultValue] = useState('');
  const [resultUnit, setResultUnit] = useState('mg/dL');
  const [criticalFlag, setCriticalFlag] = useState(false);

  const filtered = useMemo(() => {
    if (!patient) {
      return [];
    }
    const list = patient.exams;
    if (filter === 'pending') {
      return list.filter((e) => e.status === 'pending');
    }
    if (filter === 'completed') {
      return list.filter((e) => e.status === 'completed');
    }
    if (filter === 'critical') {
      return list.filter((e) => e.status === 'critical');
    }
    return list;
  }, [patient, filter]);

  if (!activePatientId || !patient) {
    return (
      <p className="text-slate-600">Selecione um paciente para ver exames.</p>
    );
  }

  function openSimulate(ex: Exam) {
    setModalExam(ex);
    setResultValue('');
    setCriticalFlag(false);
    setResultUnit(
      ex.name.toLowerCase().includes('lactato') ? 'mmol/L' : 'mg/dL',
    );
  }

  async function confirmResult() {
    if (!patient || !modalExam) {
      return;
    }
    const status = criticalFlag ? 'critical' : 'completed';
    const resultStr = `${resultValue} ${resultUnit}`.trim();
    const interpretation =
      status === 'critical'
        ? `Valor crítico registrado (${resultStr}). Avaliação urgente recomendada (mock).`
        : `Resultado ${resultStr} dentro do fluxo de demonstração.`;

    await patchPatientMock(patient.id, {
      exams: [
        {
          id: modalExam.id,
          status,
          result: resultStr,
          interpretation,
        },
      ],
    });
    await refetch();
    await refreshAlertBadge();
    showToast(
      criticalFlag
        ? 'Resultado registrado. Alerta crítico emitido para equipe médica.'
        : 'Resultado registrado.',
    );
    if (criticalFlag) {
      navigate('/alerts');
    }
    setModalExam(null);
  }

  async function notifyResponsible() {
    if (!patient || !selected) {
      return;
    }
    await addAlertMock({
      patientId: patient.id,
      severity: 'moderate',
      category: 'exam',
      message: `Notificação: revisar ${selected.name} — ${selected.result ?? 'resultado disponível'}.`,
      team: 'doctors',
      resolved: false,
    });
    await refreshAlertBadge();
    showToast('Notificação registrada.');
  }

  return (
    <div className="flex flex-col gap-4 lg:flex-row">
      <div className="min-w-0 flex-1 space-y-4">
        <h2 className="text-xl font-semibold text-slate-900">
          Exames e pendências
        </h2>
        <div className="flex flex-wrap gap-2">
          {(
            [
              ['all', 'Todos'],
              ['pending', 'Pendentes'],
              ['completed', 'Concluídos'],
              ['critical', 'Críticos'],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setFilter(key)}
              className={`rounded-full px-3 py-1 text-sm font-medium ${
                filter === key
                  ? 'bg-teal-600 text-white'
                  : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="overflow-x-auto rounded-xl border border-[var(--color-border-subtle)] bg-white">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="border-b bg-slate-50 text-xs font-semibold uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">Exame</th>
                <th className="px-3 py-2">Solicitado em</th>
                <th className="px-3 py-2">Origem</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Ação</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((ex) => (
                <tr
                  key={ex.id}
                  className={`cursor-pointer border-b hover:bg-teal-50/50 ${
                    selected?.id === ex.id ? 'bg-teal-50' : ''
                  }`}
                  onClick={() => setSelected(ex)}
                >
                  <td className="px-3 py-2 font-medium">{ex.name}</td>
                  <td className="px-3 py-2 text-slate-600">
                    {new Date(ex.requestedAt).toLocaleString('pt-BR', {
                      day: '2-digit',
                      month: '2-digit',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${
                        ex.source === 'protocol'
                          ? 'bg-sky-100 text-sky-900'
                          : 'bg-slate-100 text-slate-700'
                      }`}
                    >
                      {ex.source === 'protocol' ? 'Protocolo' : 'Manual'}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    {ex.status === 'pending'
                      ? '🟡 Pendente'
                      : ex.status === 'completed'
                        ? '✅ Concluído'
                        : '🔴 Crítico'}
                  </td>
                  <td className="px-3 py-2">
                    {ex.status === 'pending' ? (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          openSimulate(ex);
                        }}
                        className="text-teal-700 underline"
                      >
                        Simular resultado
                      </button>
                    ) : (
                      '—'
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <aside className="w-full shrink-0 rounded-xl border border-[var(--color-border-subtle)] bg-white p-4 lg:w-80">
        {!selected ? (
          <p className="text-sm text-slate-500">
            Clique em um exame para ver detalhes.
          </p>
        ) : (
          <div className="space-y-3 text-sm">
            <h3 className="font-semibold text-slate-900">{selected.name}</h3>
            <p className="text-slate-600">
              <span className="font-medium">Método:</span> análise automatizada
              (mock)
            </p>
            <p className="text-slate-600">
              <span className="font-medium">Referência:</span> valores usuais
              laboratoriais institucionais (mock)
            </p>
            {selected.result ? (
              <p>
                <span className="font-medium">Resultado:</span> {selected.result}
              </p>
            ) : null}
            {selected.interpretation ? (
              <p className="text-slate-700">
                <span className="font-medium">Interpretação do assistente:</span>{' '}
                {selected.interpretation}
              </p>
            ) : null}
            <button
              type="button"
              onClick={() => void notifyResponsible()}
              className="w-full rounded-lg border border-teal-600 py-2 text-sm font-medium text-teal-800 hover:bg-teal-50"
            >
              Notificar responsável
            </button>
          </div>
        )}
      </aside>

      {modalExam ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
          <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
            <h3 className="font-semibold text-slate-900">
              Simular resultado — {modalExam.name}
            </h3>
            <div className="mt-4 flex gap-2">
              <input
                type="text"
                value={resultValue}
                onChange={(e) => setResultValue(e.target.value)}
                placeholder="Valor"
                className="flex-1 rounded border px-3 py-2 text-sm"
              />
              <input
                value={resultUnit}
                onChange={(e) => setResultUnit(e.target.value)}
                className="w-24 rounded border px-2 py-2 text-sm"
              />
            </div>
            <label className="mt-3 flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={criticalFlag}
                onChange={(e) => setCriticalFlag(e.target.checked)}
              />
              Marcar como crítico
            </label>
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setModalExam(null)}
                className="rounded px-4 py-2 text-sm text-slate-600"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={() => void confirmResult()}
                className="rounded bg-teal-600 px-4 py-2 text-sm text-white"
              >
                Confirmar
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
