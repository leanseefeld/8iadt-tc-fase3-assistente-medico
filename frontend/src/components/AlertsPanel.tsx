import { Bell } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { ClinicalAlert } from '@/types/alert';
import { getAlertsForPatientMock } from '@/api/mockApi';
import { MOCK_ALERTS } from '@/api/mockData';
import { usePatientContext } from '@/context/PatientContext';

const SEVERITY_LABEL: Record<ClinicalAlert['severity'], string> = {
  info: 'Informação',
  warning: 'Atenção',
  critical: 'Crítico',
};

const SEVERITY_STYLE: Record<ClinicalAlert['severity'], string> = {
  info: 'bg-sky-100 text-sky-900',
  warning: 'bg-amber-100 text-amber-900',
  critical: 'bg-red-100 text-red-900',
};

function formatDateTime(iso: string): string {
  try {
    return new Intl.DateTimeFormat('pt-BR', {
      dateStyle: 'short',
      timeStyle: 'short',
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

export function AlertsTriggerAndPanel() {
  const { selectedPatient } = usePatientContext();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [alerts, setAlerts] = useState<ClinicalAlert[]>([]);
  const [loading, setLoading] = useState(false);

  const badgeCount = useMemo(
    () => MOCK_ALERTS.filter((a) => a.patientId === selectedPatient.id).length,
    [selectedPatient.id],
  );

  async function openPanel() {
    const d = dialogRef.current;
    if (!d) {
      return;
    }
    d.showModal();
    setLoading(true);
    const list = await getAlertsForPatientMock(selectedPatient.id);
    setAlerts(list);
    setLoading(false);
  }

  function closePanel() {
    dialogRef.current?.close();
  }

  useEffect(() => {
    const d = dialogRef.current;
    if (!d) {
      return;
    }
    function onClose() {
      setAlerts([]);
    }
    d.addEventListener('close', onClose);
    return () => d.removeEventListener('close', onClose);
  }, []);

  return (
    <>
      <button
        type="button"
        onClick={() => void openPanel()}
        className="relative flex h-10 w-10 items-center justify-center rounded-lg border border-[var(--color-border-subtle)] bg-white text-slate-600 shadow-sm transition-colors hover:border-teal-300 hover:text-teal-700"
        aria-label="Abrir alertas do paciente"
      >
        <Bell className="h-5 w-5" aria-hidden />
        {badgeCount > 0 ? (
          <span className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-amber-500 px-1 text-[10px] font-bold text-white">
            {badgeCount > 9 ? '9+' : badgeCount}
          </span>
        ) : null}
      </button>

      <dialog
        ref={dialogRef}
        className="fixed left-1/2 top-1/2 z-50 max-h-[min(90vh,32rem)] w-[min(calc(100vw-2rem),28rem)] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-[var(--color-border-subtle)] bg-white p-0 shadow-2xl backdrop:bg-slate-900/40"
        onClick={(e) => {
          if (e.target === dialogRef.current) {
            closePanel();
          }
        }}
      >
        <div className="border-b border-[var(--color-border-subtle)] px-4 py-3">
          <h2 className="text-base font-semibold text-slate-800">
            Alertas — {selectedPatient.name}
          </h2>
          <p className="text-xs text-slate-500">
            Dados simulados para demonstração
          </p>
        </div>
        <div className="max-h-[min(70vh,24rem)] overflow-y-auto p-3">
          {loading ? (
            <p className="px-1 py-4 text-center text-sm text-slate-500">
              Carregando alertas…
            </p>
          ) : alerts.length === 0 ? (
            <p className="px-1 py-4 text-center text-sm text-slate-500">
              Nenhum alerta para este paciente.
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {alerts.map((a) => (
                <li
                  key={a.id}
                  className="rounded-lg border border-[var(--color-border-subtle)] bg-slate-50/80 p-3"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${SEVERITY_STYLE[a.severity]}`}
                    >
                      {SEVERITY_LABEL[a.severity]}
                    </span>
                    <time
                      className="text-xs text-slate-500"
                      dateTime={a.createdAt}
                    >
                      {formatDateTime(a.createdAt)}
                    </time>
                  </div>
                  <p className="mt-1 font-medium text-slate-800">{a.title}</p>
                  <p className="mt-1 text-sm text-slate-600">{a.message}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="border-t border-[var(--color-border-subtle)] px-4 py-3 text-right">
          <button
            type="button"
            onClick={closePanel}
            className="rounded-lg bg-slate-200 px-4 py-2 text-sm font-medium text-slate-800 hover:bg-slate-300"
          >
            Fechar
          </button>
        </div>
      </dialog>
    </>
  );
}
