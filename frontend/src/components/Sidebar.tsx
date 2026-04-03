import { NavLink } from 'react-router-dom';
import { useAppSession } from '@/context/AppSessionContext';

const NAV: { to: string; label: string; showBadge?: boolean }[] = [
  { to: '/checkin', label: '➕ Check-in / Admissão' },
  { to: '/dashboard', label: '🏠 Dashboard' },
  { to: '/chat', label: '💬 Chat com Assistente' },
  { to: '/flow', label: '🔀 Fluxo de Decisão' },
  { to: '/exams', label: '🧪 Exames' },
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
    <aside className="flex w-60 shrink-0 flex-col border-r border-[var(--color-border-subtle)] bg-[var(--color-surface-elevated)] shadow-sm">
      <div className="border-b border-[var(--color-border-subtle)] px-4 py-5">
        <h1 className="text-lg font-semibold tracking-tight text-teal-800">
          Assistente Médico IA
        </h1>
        <p className="mt-1 text-xs text-slate-500">Protótipo de interface</p>
      </div>

      <div className="border-b border-[var(--color-border-subtle)] px-3 py-3">
        <label className="text-xs font-medium text-slate-500">
          Paciente ativo
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
        <p className="mt-2 flex items-center gap-1.5 text-xs text-slate-600">
          <span className="h-2 w-2 rounded-full bg-emerald-500" aria-hidden />
          <span>Agente ativo</span>
        </p>
      </div>

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
    </aside>
  );
}
