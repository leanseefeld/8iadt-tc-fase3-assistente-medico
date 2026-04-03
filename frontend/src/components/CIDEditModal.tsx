import { Search } from 'lucide-react';
import { useEffect, useId, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getCidListMock, patchPatientMock } from '@/api/clinicalApi';
import { useAppSession } from '@/context/AppSessionContext';
import { useToast } from '@/context/ToastContext';
import type { Cid, Patient } from '@/types/domain';

export interface CIDEditModalProps {
  open: boolean;
  patient: Patient | null;
  onClose: () => void;
  onSaved?: () => void;
}

export function CIDEditModal({
  open,
  patient,
  onClose,
  onSaved,
}: CIDEditModalProps) {
  const navigate = useNavigate();
  const { showToast } = useToast();
  const {
    refreshAdmittedPatients,
    setPendingFlowReview,
  } = useAppSession();
  const dialogId = useId();
  const [cids, setCids] = useState<Cid[]>([]);
  const [q, setQ] = useState('');
  const [selected, setSelected] = useState<Cid | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) {
      return;
    }
    void getCidListMock().then(setCids);
    setQ('');
    setSelected(patient ? { ...patient.cid } : null);
  }, [open, patient]);

  if (!open || !patient) {
    return null;
  }

  const filtered = cids.filter(
    (c) =>
      c.code.toLowerCase().includes(q.trim().toLowerCase()) ||
      c.label.toLowerCase().includes(q.trim().toLowerCase()),
  );

  const cidChanged =
    selected != null && selected.code !== patient.cid.code;

  async function confirm() {
    if (!selected || !patient || selected.code === patient.cid.code) {
      return;
    }
    setSaving(true);
    const updated = await patchPatientMock(patient.id, { cid: selected });
    setSaving(false);
    if (!updated) {
      showToast('Não foi possível atualizar o CID.');
      return;
    }
    await refreshAdmittedPatients();
    showToast('CID atualizado. Fluxo de decisão re-executado.');
    setPendingFlowReview(true);
    onSaved?.();
    onClose();
    navigate('/flow');
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby={dialogId}
    >
      <div className="max-h-[90vh] w-full max-w-lg overflow-hidden rounded-xl border border-[var(--color-border-subtle)] bg-white shadow-2xl">
        <div className="border-b border-[var(--color-border-subtle)] px-4 py-3">
          <h2 id={dialogId} className="text-lg font-semibold text-slate-900">
            Editar CID principal
          </h2>
          <p className="mt-1 text-sm text-slate-600">
            Busque e selecione o CID que substituirá o atual (
            <span className="font-mono text-slate-800">{patient.cid.code}</span>
            ).
          </p>
          {cidChanged ? (
            <p className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-950">
              Ao confirmar, o protocolo será atualizado e novos exames ou ações
              podem ser identificados. Revise o fluxo de decisão em seguida.
            </p>
          ) : null}
        </div>
        <div className="space-y-3 p-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Buscar por código ou descrição…"
              className="w-full rounded-lg border border-[var(--color-border-subtle)] py-2 pl-9 pr-3 text-sm outline-none focus:ring-2 focus:ring-teal-500"
            />
          </div>
          <ul className="max-h-48 overflow-auto rounded-lg border border-[var(--color-border-subtle)]">
            {filtered.map((c) => (
              <li key={c.code}>
                <button
                  type="button"
                  onClick={() => setSelected(c)}
                  className={`flex w-full flex-col items-start px-3 py-2 text-left text-sm hover:bg-teal-50 ${
                    selected?.code === c.code ? 'bg-teal-100' : ''
                  }`}
                >
                  <span className="font-mono text-xs text-slate-500">
                    {c.code}
                  </span>
                  <span className="font-medium text-slate-800">{c.label}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
        <div className="flex justify-end gap-2 border-t border-[var(--color-border-subtle)] px-4 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100"
          >
            Cancelar
          </button>
          <button
            type="button"
            disabled={!selected || saving || !cidChanged}
            onClick={() => void confirm()}
            className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-50"
          >
            Confirmar
          </button>
        </div>
      </div>
    </div>
  );
}
