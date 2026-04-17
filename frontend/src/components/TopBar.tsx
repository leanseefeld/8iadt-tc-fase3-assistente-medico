import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { patchPatientMock } from '@/api/clinicalApi';
import { CIDEditModal } from '@/components/CIDEditModal';
import { useAppSession } from '@/context/AppSessionContext';
import { useToast } from '@/context/ToastContext';
import { usePatientDetail } from '@/hooks/usePatientDetail';

function formatSexDisplay(sex: 'M' | 'F'): string {
  return sex === 'F' ? 'Feminino' : 'Masculino';
}

function formatAdmission(iso: string): string {
  try {
    return new Intl.DateTimeFormat('pt-BR', {
      dateStyle: 'short',
      timeStyle: 'short',
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

export function TopBar() {
  const navigate = useNavigate();
  const { showToast } = useToast();
  const { activePatientId, refreshAdmittedPatients, refreshAlertBadge } =
    useAppSession();
  const { patient, refetch } = usePatientDetail(activePatientId);
  const [cidOpen, setCidOpen] = useState(false);
  const [dischargeOpen, setDischargeOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  async function confirmDischarge() {
    if (!patient) {
      return;
    }
    setBusy(true);
    const updated = await patchPatientMock(patient.id, {
      status: 'discharged',
    });
    setBusy(false);
    setDischargeOpen(false);
    if (!updated) {
      showToast('Não foi possível registrar a alta.');
      return;
    }
    showToast(`Paciente ${patient.name} recebeu alta com sucesso.`);
    await refreshAdmittedPatients();
    await refreshAlertBadge();
    refetch();
    navigate('/checkin');
  }

  if (!activePatientId || !patient) {
    return (
      <header className="flex min-h-16 shrink-0 items-center border-b border-[var(--color-border-subtle)] bg-[var(--color-surface-elevated)] px-4 py-3 shadow-sm">
        <p className="text-sm text-slate-600">
          Selecione um paciente admitido ou realize um check-in.
        </p>
      </header>
    );
  }

  return (
    <>
      <header className="flex min-h-16 shrink-0 flex-wrap items-center gap-4 border-b border-[var(--color-border-subtle)] bg-[var(--color-surface-elevated)] px-4 py-3 shadow-sm">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Paciente
          </p>
          <button
            type="button"
            onClick={() => setCidOpen(true)}
            className="truncate text-left text-lg font-semibold text-teal-900 underline decoration-teal-300 decoration-2 underline-offset-2 hover:text-teal-950"
          >
            {patient.name}
          </button>
          <p className="mt-0.5 text-sm text-slate-600">
            CID {patient.cid.code} — {patient.cid.label}
          </p>
          <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-sm">
            <div>
              <dt className="text-xs text-slate-500">Sexo</dt>
              <dd className="font-medium text-slate-800">
                {formatSexDisplay(patient.sex)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Idade</dt>
              <dd className="font-medium text-slate-800">{patient.age} anos</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Admissão</dt>
              <dd className="font-medium text-slate-800">
                {formatAdmission(patient.admittedAt)}
              </dd>
            </div>
          </dl>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setCidOpen(true)}
            className="rounded-lg border border-teal-600 px-3 py-2 text-sm font-medium text-teal-800 hover:bg-teal-50"
          >
            Editar CID
          </button>
          <button
            type="button"
            onClick={() => setDischargeOpen(true)}
            className="rounded-lg border border-red-400 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-50"
          >
            Alta
          </button>
        </div>
      </header>

      <CIDEditModal
        open={cidOpen}
        patient={patient}
        onClose={() => setCidOpen(false)}
        onSaved={() => {
          void refetch();
          void refreshAlertBadge();
        }}
      />

      {dischargeOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
          <div className="w-full max-w-md rounded-xl border border-[var(--color-border-subtle)] bg-white p-6 shadow-xl">
            <p className="text-slate-800">
              Confirmar alta de <strong>{patient.name}</strong>?
            </p>
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setDischargeOpen(false)}
                className="rounded-lg px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100"
              >
                Cancelar
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void confirmDischarge()}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
              >
                Confirmar alta
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
