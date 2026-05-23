import { NavLink } from 'react-router-dom';
import { useAppSession } from '@/context/AppSessionContext';

const NAV: { to: string; label: string; showBadge?: boolean }[] = [
  { to: '/dashboard', label: '🏠 Dashboard' },
  { to: '/chat', label: '💬 Chat com Assistente' },
  { to: '/flow', label: '🔀 Fluxo de Decisão' },
  { to: '/exams', label: '🧪 Exames' },
  { to: '/prescriptions', label: '💊 Prescrições' },
  { to: '/suggested-actions', label: '📋 Ações Sugeridas' },
  { to: '/alerts', label: '🔔 Alertas', showBadge: true },
];

export function Sidebar() {
  const {
    admittedPatients,
    activePatientId,
    setActivePatientId,
    unresolvedAlertCount,
  } = useAppSession();

  return (
    <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col overflow-y-auto border-r border-[var(--color-border-subtle)] bg-[var(--color-surface-elevated)] shadow-sm">
      <div className="border-b border-[var(--color-border-subtle)] px-4 py-5">
        <h1 className="text-lg font-semibold tracking-tight text-teal-800">
          Assistente Médico
        </h1>

        <NavLink
          to="/checkin"
          className={({ isActive }) =>
            [
              'mt-4 flex items-center justify-center rounded-xl px-4 py-3 text-sm font-extrabold shadow-sm ring-1 transition-all',
              isActive
                ? 'bg-teal-600 text-white ring-teal-600 shadow-teal-200'
                : 'bg-teal-100 text-teal-950 ring-teal-300 hover:bg-teal-200 hover:shadow-md',
            ].join(' ')
          }
        >
          Nova Admissão
        </NavLink>
      </div>

      <div className="border-b border-[var(--color-border-subtle)] px-3 py-3">
        <label className="text-xs font-medium text-slate-500">
          Paciente:
        </label>
        {admittedPatients.length === 0 ? (
          <p className="mt-2 text-xs leading-relaxed text-slate-600">
            Nenhum paciente ativo. Realize um{' '}
            <NavLink to="/checkin" className="font-medium text-teal-700 underline">
              check-in
            </NavLink>
            .
          </p>
        ) : (
          <select
            value={activePatientId ?? ''}
            onChange={(e) =>
              setActivePatientId(e.target.value ? e.target.value : null)
            }
            className="mt-2 w-full rounded-lg border border-[var(--color-border-subtle)] bg-white px-2 py-2 text-sm text-slate-800"
          >
            {admittedPatients.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        )}
        
        <nav className="flex flex-1 flex-col gap-0.5 p-2" aria-label="Principal">
          {NAV.map(({ to, label, showBadge }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                [
                  'flex items-center justify-between rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-teal-600 text-white'
                    : 'text-slate-700 hover:bg-slate-100',
                ].join(' ')
              }
            >
              <span>{label}</span>
              {showBadge && unresolvedAlertCount > 0 ? (
                <span className="rounded-full bg-amber-500 px-1.5 text-[10px] font-bold text-white">
                  {unresolvedAlertCount > 99 ? '99+' : unresolvedAlertCount}
                </span>
              ) : null}
            </NavLink>
          ))}
        </nav>
      </div>

    </aside>
  );
}
