import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  getAlertsMock,
  getPatientsMock,
  patchAlertMock,
} from '@/api/clinicalApi';
import { useAppSession } from '@/context/AppSessionContext';
import type { Alert, AlertSeverity, AlertTeam } from '@/types/alert';

const SEVERITY_LABEL: Record<AlertSeverity, string> = {
  critical: 'Crítico',
  moderate: 'Moderado',
  info: 'Informativo',
};

const TEAM_LABEL: Record<AlertTeam | 'all', string> = {
  doctors: 'Médicos',
  nursing: 'Enfermagem',
  pharmacy: 'Farmácia',
  all: 'Todos',
};

export function AlertsPage() {
  const { setActivePatientId, refreshAlertBadge } = useAppSession();
  const [allAlerts, setAllAlerts] = useState<Alert[]>([]);
  const [patientNames, setPatientNames] = useState<Record<string, string>>({});
  const [sevFilter, setSevFilter] = useState<AlertSeverity | 'all'>('all');
  const [teamFilter, setTeamFilter] = useState<AlertTeam | 'all'>('all');
  const [resolvedOpen, setResolvedOpen] = useState(false);

  const load = useCallback(async () => {
    const raw = await getAlertsMock();
    let list = raw;
    if (sevFilter !== 'all') {
      list = list.filter((a) => a.severity === sevFilter);
    }
    if (teamFilter !== 'all') {
      list = list.filter(
        (a) => a.team === teamFilter || a.team === 'all',
      );
    }
    setAllAlerts(list);
    const patients = await getPatientsMock();
    const map: Record<string, string> = { system: 'Sistema' };
    for (const p of patients) {
      map[p.id] = p.name;
    }
    setPatientNames(map);
  }, [sevFilter, teamFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const openAlerts = allAlerts.filter((a) => !a.resolved);
  const closedAlerts = allAlerts.filter((a) => a.resolved);

  async function resolveAlert(id: string) {
    await patchAlertMock(id, { resolved: true });
    await refreshAlertBadge();
    void load();
  }

  const mockChart = [
    { label: 'Exames críticos', value: 8 },
    { label: 'Medicamentos', value: 3 },
    { label: 'Clínicos', value: 5 },
  ];

  function renderCard(a: Alert) {
    return (
      <li
        key={a.id}
        className="rounded-xl border border-[var(--color-border-subtle)] bg-white p-4 shadow-sm"
      >
        <div className="flex flex-wrap items-center gap-2">
          <span aria-hidden>
            {a.severity === 'critical'
              ? '🔴'
              : a.severity === 'moderate'
                ? '🟡'
                : '🔵'}
          </span>
          <span className="font-medium text-slate-900">
            {SEVERITY_LABEL[a.severity]} · {a.category}
          </span>
          <time className="text-xs text-slate-500" dateTime={a.createdAt}>
            {new Date(a.createdAt).toLocaleString('pt-BR')}
          </time>
        </div>
        {a.patientId !== 'system' ? (
          <Link
            to="/dashboard"
            onClick={() => setActivePatientId(a.patientId)}
            className="mt-1 inline-block text-sm text-teal-700 underline"
          >
            {patientNames[a.patientId] ?? a.patientId}
          </Link>
        ) : (
          <p className="mt-1 text-sm text-slate-600">Sistema</p>
        )}
        <p className="mt-2 text-sm text-slate-700">{a.message}</p>
        {!a.resolved ? (
          <button
            type="button"
            onClick={() => void resolveAlert(a.id)}
            className="mt-3 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium hover:bg-slate-50"
          >
            Marcar como resolvido
          </button>
        ) : (
          <p className="mt-2 text-xs text-slate-500">Resolvido</p>
        )}
      </li>
    );
  }

  return (
    <div className="flex flex-col gap-6 lg:flex-row">
      <div className="min-w-0 flex-1 space-y-4">
        <h2 className="text-xl font-semibold text-slate-900">Alertas</h2>
        <div className="flex flex-wrap gap-2">
          {(['all', 'critical', 'moderate', 'info'] as const).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setSevFilter(s === 'all' ? 'all' : s)}
              className={`rounded-full px-3 py-1 text-xs font-medium ${
                (s === 'all' && sevFilter === 'all') || sevFilter === s
                  ? 'bg-teal-600 text-white'
                  : 'bg-slate-100 text-slate-700'
              }`}
            >
              {s === 'all' ? 'Todas severidades' : SEVERITY_LABEL[s]}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          {(['all', 'doctors', 'nursing', 'pharmacy'] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTeamFilter(t)}
              className={`rounded-full px-3 py-1 text-xs font-medium ${
                teamFilter === t
                  ? 'bg-slate-800 text-white'
                  : 'bg-slate-100 text-slate-700'
              }`}
            >
              {t === 'all' ? 'Todas equipes' : TEAM_LABEL[t]}
            </button>
          ))}
        </div>

        <h3 className="text-sm font-semibold text-slate-700">Não resolvidos</h3>
        <ul className="space-y-3">{openAlerts.map(renderCard)}</ul>

        <button
          type="button"
          onClick={() => setResolvedOpen((o) => !o)}
          className="text-sm font-medium text-slate-600 underline"
        >
          Resolvidos ({closedAlerts.length}) {resolvedOpen ? '▼' : '▶'}
        </button>
        {resolvedOpen ? (
          <ul className="space-y-3 opacity-80">
            {closedAlerts.map(renderCard)}
          </ul>
        ) : null}
      </div>

      <aside className="w-full shrink-0 space-y-3 lg:w-64">
        <h3 className="text-sm font-semibold text-slate-800">
          Volume mock (última semana)
        </h3>
        <div className="space-y-2 rounded-xl border bg-white p-4">
          {mockChart.map((row) => (
            <div key={row.label}>
              <div className="flex justify-between text-xs text-slate-600">
                <span>{row.label}</span>
                <span>{row.value}</span>
              </div>
              <div className="mt-1 h-2 overflow-hidden rounded bg-slate-100">
                <div
                  className="h-full bg-teal-500"
                  style={{ width: `${Math.min(100, row.value * 10)}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </aside>
    </div>
  );
}
