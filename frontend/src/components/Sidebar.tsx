import { NavLink } from 'react-router-dom';

const NAV = [
  { to: '/', label: 'Painel' },
  { to: '/chat', label: 'Chat' },
  { to: '/decision-flow', label: 'Fluxo de decisão' },
  { to: '/exams-pendencies', label: 'Exames e pendências' },
  { to: '/suggested-actions', label: 'Ações sugeridas' },
] as const;

export function Sidebar() {
  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-[var(--color-border-subtle)] bg-[var(--color-surface-elevated)] shadow-sm">
      <div className="border-b border-[var(--color-border-subtle)] px-4 py-5">
        <h1 className="text-lg font-semibold tracking-tight text-teal-800">
          Assistente Médico IA
        </h1>
        <p className="mt-1 text-xs text-slate-500">Protótipo de interface</p>
      </div>
      <nav className="flex flex-1 flex-col gap-0.5 p-2" aria-label="Principal">
        {NAV.map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              [
                'rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-teal-600 text-white'
                  : 'text-slate-700 hover:bg-slate-100',
              ].join(' ')
            }
          >
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
