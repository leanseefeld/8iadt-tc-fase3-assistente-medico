import { CheckInBadge } from '@/components/CheckInBadge';
import { PatientLookup } from '@/components/PatientLookup';
import { AlertsTriggerAndPanel } from '@/components/AlertsPanel';
import { usePatientContext } from '@/context/PatientContext';

export function TopBar() {
  const { selectedPatient: p } = usePatientContext();

  return (
    <header className="flex min-h-16 shrink-0 flex-wrap items-center gap-4 border-b border-[var(--color-border-subtle)] bg-[var(--color-surface-elevated)] px-4 py-3 shadow-sm">
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-6 gap-y-2">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Paciente
          </p>
          <p className="truncate text-lg font-semibold text-slate-900">
            {p.name}
          </p>
        </div>
        <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
          <div>
            <dt className="text-xs text-slate-500">Sexo</dt>
            <dd className="font-medium text-slate-800">{p.gender}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">Idade</dt>
            <dd className="font-medium text-slate-800">{p.age} anos</dd>
          </div>
          <div className="min-w-[8rem] max-w-xs sm:max-w-md">
            <dt className="text-xs text-slate-500">Condição principal</dt>
            <dd className="font-medium text-slate-800">{p.mainCondition}</dd>
          </div>
          <div className="flex items-end">
            <CheckInBadge patient={p} />
          </div>
        </dl>
      </div>
      <div className="ml-auto flex shrink-0 items-center gap-2">
        <PatientLookup />
        <AlertsTriggerAndPanel />
      </div>
    </header>
  );
}
