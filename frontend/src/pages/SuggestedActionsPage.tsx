import { useMemo, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { FileText } from 'lucide-react';
import { patchPatientMock } from '@/api/clinicalApi';
import { useAppSession } from '@/context/AppSessionContext';
import { usePatientDetail } from '@/hooks/usePatientDetail';
import type { SuggestedActionItem, SuggestedActionType } from '@/types/domain';

const TYPE_ORDER: SuggestedActionType[] = [
  'exam',
  'prescription',
  'observation',
  'review',
];

const TYPE_HEADINGS: Record<SuggestedActionType, string> = {
  exam: '📋 Exames a solicitar',
  prescription: '💊 Prescrições',
  observation: '📝 Observações de enfermagem',
  review: '🔄 Revisão',
};

export function SuggestedActionsPage() {
  const { admittedPatients, activePatientId } = useAppSession();
  const { patient, refetch } = usePatientDetail(activePatientId);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState('');

  const suggestedItems = patient?.suggestedItems ?? [];
  const grouped = useMemo(() => {
    const g = new Map<SuggestedActionType, SuggestedActionItem[]>();
    for (const t of TYPE_ORDER) {
      g.set(t, []);
    }
    for (const item of suggestedItems) {
      g.get(item.type)?.push(item);
    }
    return g;
  }, [suggestedItems]);

  if (admittedPatients.length === 0) {
    return <Navigate to="/checkin" replace />;
  }

  if (!activePatientId || !patient) {
    return (
      <p className="text-slate-600">Selecione um paciente admitido.</p>
    );
  }

  const p = patient;

  const protocolRef =
    p.suggestedItems[0]?.protocolRef ??
    p.exams[0]?.protocolRef ??
    'Protocolo (mock)';

  async function patchItem(
    id: string,
    partial: Partial<SuggestedActionItem>,
  ) {
    await patchPatientMock(p.id, {
      suggestedItems: [{ id, ...partial }],
    });
    await refetch();
    setEditingId(null);
  }

  async function acceptAllSuggested() {
    const patches = p.suggestedItems
      .filter((i) => i.status === 'suggested')
      .map((i) => ({ id: i.id, status: 'accepted' as const }));
    if (!patches.length) {
      return;
    }
    await patchPatientMock(p.id, { suggestedItems: patches });
    await refetch();
  }

  function startModify(item: SuggestedActionItem) {
    setEditingId(item.id);
    setEditText(item.description);
  }

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="rounded-xl border border-[var(--color-border-subtle)] bg-white p-5 shadow-sm">
        <h2 className="text-xl font-semibold text-slate-900">Resumo do caso</h2>
        <p className="mt-3 text-sm font-medium text-slate-800">
          Hipótese (mock): {p.cid.label} ({p.cid.code})
        </p>
        <p className="mt-2 text-sm leading-relaxed text-slate-700">
          Paciente internado com queixa principal descrita no check-in. Contexto
          simulado para demonstração: {p.observations.slice(0, 200)}
          {p.observations.length > 200 ? '…' : ''}
        </p>
        <p className="mt-3 text-sm text-teal-800">
          <a
            href="#"
            className="font-medium underline"
            onClick={(e) => e.preventDefault()}
          >
            {protocolRef}
          </a>
        </p>
      </div>

      <div className="rounded-xl border border-[var(--color-border-subtle)] bg-white p-5 shadow-sm">
        <div className="flex items-start justify-between gap-2">
          <h2 className="text-xl font-semibold text-slate-900">
            Ações sugeridas
          </h2>
          <button
            type="button"
            onClick={() => void acceptAllSuggested()}
            className="shrink-0 rounded-lg bg-teal-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-teal-700"
          >
            Aceitar tudo
          </button>
        </div>

        <div className="mt-4 space-y-6">
          {TYPE_ORDER.map((type) => {
            const items = grouped.get(type) ?? [];
            if (!items.length) {
              return null;
            }
            return (
              <div key={type}>
                <h3 className="text-sm font-semibold text-slate-800">
                  {TYPE_HEADINGS[type]}
                </h3>
                <ul className="mt-2 space-y-2">
                  {items.map((item) => (
                    <li
                      key={item.id}
                      className={`rounded-lg border border-slate-100 bg-slate-50/80 p-3 text-sm ${
                        item.status === 'rejected'
                          ? 'opacity-60 line-through'
                          : ''
                      }`}
                    >
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <span>
                          {item.status === 'accepted' ? '✅ ' : '☐ '}
                          {editingId === item.id ? (
                            <span className="flex flex-col gap-2">
                              <textarea
                                value={editText}
                                onChange={(e) => setEditText(e.target.value)}
                                rows={2}
                                className="w-full rounded border px-2 py-1 text-sm"
                              />
                              <button
                                type="button"
                                onClick={() =>
                                  void patchItem(item.id, {
                                    description: editText,
                                    status: 'modified',
                                  })
                                }
                                className="self-start rounded bg-teal-600 px-2 py-1 text-xs text-white"
                              >
                                Salvar
                              </button>
                            </span>
                          ) : (
                            <>
                              {item.description}
                              {item.status === 'modified' ? (
                                <span className="ml-2 rounded bg-amber-100 px-1.5 text-xs text-amber-900">
                                  Modificado
                                </span>
                              ) : null}
                            </>
                          )}
                        </span>
                        <div className="flex gap-1">
                          {item.status !== 'rejected' &&
                          item.status !== 'accepted' ? (
                            <>
                              <button
                                type="button"
                                onClick={() =>
                                  void patchItem(item.id, {
                                    status: 'accepted',
                                  })
                                }
                                className="rounded border border-emerald-600 px-2 py-0.5 text-xs text-emerald-800"
                              >
                                Aceitar
                              </button>
                              <button
                                type="button"
                                onClick={() => startModify(item)}
                                className="rounded border border-slate-300 px-2 py-0.5 text-xs"
                              >
                                Modificar
                              </button>
                              <button
                                type="button"
                                title="Rejeitar"
                                onClick={() =>
                                  void patchItem(item.id, {
                                    status: 'rejected',
                                  })
                                }
                                className="rounded border border-red-200 px-2 py-0.5 text-xs text-red-700 opacity-70 hover:opacity-100"
                              >
                                ✕
                              </button>
                            </>
                          ) : null}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>

        <div className="mt-8 border-t pt-4 text-sm text-slate-600">
          <p className="flex items-center gap-2">
            <FileText className="h-4 w-4" aria-hidden />
            Protocolo: {protocolRef}
          </p>
          <p className="mt-2 italic text-slate-500">
            Esta é uma sugestão. A decisão final é do médico responsável.
          </p>
        </div>
      </div>
    </div>
  );
}
