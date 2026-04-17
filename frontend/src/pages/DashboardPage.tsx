import { useState } from 'react';
import { Link } from 'react-router-dom';
import { patchPatientMock } from '@/api/clinicalApi';
import { CIDEditModal } from '@/components/CIDEditModal';
import { useAppSession } from '@/context/AppSessionContext';
import { useToast } from '@/context/ToastContext';
import { usePatientDetail } from '@/hooks/usePatientDetail';

function vitalStatus(
  key: 'bloodPressure' | 'temperature' | 'oxygenSaturation' | 'heartRate',
  value: number | string,
): 'normal' | 'warn' | 'crit' {
  if (key === 'oxygenSaturation') {
    const v = value as number;
    if (v < 90) {
      return 'crit';
    }
    if (v < 94) {
      return 'warn';
    }
  }
  if (key === 'temperature') {
    const v = value as number;
    if (v >= 39 || v < 35) {
      return 'crit';
    }
    if (v >= 38) {
      return 'warn';
    }
  }
  if (key === 'heartRate') {
    const v = value as number;
    if (v > 120 || v < 45) {
      return 'crit';
    }
    if (v > 100) {
      return 'warn';
    }
  }
  if (key === 'bloodPressure') {
    const s = String(value);
    const sys = Number(s.split('/')[0]);
    if (!Number.isNaN(sys) && sys >= 180) {
      return 'crit';
    }
    if (!Number.isNaN(sys) && sys >= 140) {
      return 'warn';
    }
  }
  return 'normal';
}

function statusLabel(s: 'normal' | 'warn' | 'crit'): string {
  if (s === 'crit') {
    return 'Crítico';
  }
  if (s === 'warn') {
    return 'Atenção';
  }
  return 'Normal';
}

function statusStyle(s: 'normal' | 'warn' | 'crit'): string {
  if (s === 'crit') {
    return 'border-red-300 bg-red-50 text-red-900';
  }
  if (s === 'warn') {
    return 'border-amber-300 bg-amber-50 text-amber-900';
  }
  return 'border-emerald-200 bg-emerald-50 text-emerald-900';
}

export function DashboardPage() {
  const { showToast } = useToast();
  const { activePatientId, refreshAlertBadge } = useAppSession();
  const { patient, refetch } = usePatientDetail(activePatientId);
  const [cidOpen, setCidOpen] = useState(false);
  const [vitalOpen, setVitalOpen] = useState(false);
  const [vField, setVField] = useState<'spo2' | 'temp' | 'hr' | 'bp'>('spo2');
  const [vValue, setVValue] = useState('');

  if (!activePatientId || !patient) {
    return (
      <p className="text-slate-600">
        Selecione um paciente na barra lateral ou faça um check-in.
      </p>
    );
  }

  const vs = patient.vitalSigns;
  const metrics = [
    { key: 'bloodPressure' as const, label: 'PA', value: vs.bloodPressure },
    { key: 'temperature' as const, label: 'Temp (°C)', value: vs.temperature },
    {
      key: 'oxygenSaturation' as const,
      label: 'SpO₂ (%)',
      value: vs.oxygenSaturation,
    },
    { key: 'heartRate' as const, label: 'FC (bpm)', value: vs.heartRate },
  ];

  const pendingExams = patient.exams.filter((e) => e.status === 'pending').length;

  async function applyVitalSimulation() {
    if (!patient) {
      return;
    }
    let patch: Parameters<typeof patchPatientMock>[1] = {};
    if (vField === 'spo2') {
      const n = Number(vValue);
      patch = {
        vitalSigns: { ...vs, oxygenSaturation: n },
      };
    } else if (vField === 'temp') {
      patch = { vitalSigns: { ...vs, temperature: Number(vValue) } };
    } else if (vField === 'hr') {
      patch = { vitalSigns: { ...vs, heartRate: Number(vValue) } };
    } else {
      patch = { vitalSigns: { ...vs, bloodPressure: vValue.trim() } };
    }
    const updated = await patchPatientMock(patient.id, patch);
    if (updated && patch.vitalSigns?.oxygenSaturation != null) {
      if (patch.vitalSigns.oxygenSaturation < 92) {
        showToast('SpO₂ crítica — alerta emitido para a equipe médica.');
      }
    }
    await refreshAlertBadge();
    await refetch();
    setVitalOpen(false);
    setVValue('');
  }

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-xl font-semibold text-slate-900">
          Dashboard do paciente
        </h2>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="rounded-xl border border-[var(--color-border-subtle)] bg-white p-4 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-800">Identificação</h3>
          <p className="mt-2 font-medium text-slate-900">{patient.name}</p>
          <p className="text-sm text-slate-600">
            {patient.sex === 'F' ? 'Feminino' : 'Masculino'}, {patient.age} anos
          </p>
          <button
            type="button"
            onClick={() => setCidOpen(true)}
            className="mt-2 text-left text-sm text-teal-700 underline"
          >
            {patient.cid.code} — {patient.cid.label}
          </button>
          <div className="mt-3 flex flex-wrap gap-1">
            {patient.comorbidities.map((c) => (
              <span
                key={c}
                className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-700"
              >
                {c}
              </span>
            ))}
          </div>
          <p className="mt-3 text-xs text-slate-500">
            Alta disponível na barra superior.
          </p>
        </div>

        <div className="rounded-xl border border-[var(--color-border-subtle)] bg-white p-4 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-800">Sinais vitais</h3>
          <p className="mt-1 text-xs text-slate-500">
            Atualizado em{' '}
            {new Date(vs.updatedAt).toLocaleString('pt-BR', {
              dateStyle: 'short',
              timeStyle: 'short',
            })}
          </p>
          <div className="mt-3 grid grid-cols-2 gap-2">
            {metrics.map((m) => {
              const st = vitalStatus(m.key, m.value);
              return (
                <div
                  key={m.key}
                  className={`rounded-lg border px-2 py-3 ${statusStyle(st)}`}
                >
                  <p className="text-xs font-medium opacity-80">{m.label}</p>
                  <p className="text-lg font-semibold">{m.value}</p>
                  <p className="text-[10px] font-medium">{statusLabel(st)}</p>
                </div>
              );
            })}
          </div>
          <button
            type="button"
            onClick={() => setVitalOpen(true)}
            className="mt-3 w-full rounded-lg border border-slate-200 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Simular novo valor
          </button>
        </div>

        <div className="rounded-xl border border-[var(--color-border-subtle)] bg-white p-4 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-800">Resumo ativo</h3>
          <p className="mt-2 text-xs font-medium text-slate-500">
            Medicamentos em uso
          </p>
          <ul className="mt-1 list-inside list-disc text-sm text-slate-700">
            {patient.currentMedications.length ? (
              patient.currentMedications.map((m) => <li key={m}>{m}</li>)
            ) : (
              <li className="list-none text-slate-500">Nenhum registrado</li>
            )}
          </ul>
          <p className="mt-4 text-xs font-medium text-slate-500">Exames</p>
          <p className="text-sm text-slate-800">
            {pendingExams} pendente(s){' '}
            <Link to="/exams" className="text-teal-700 underline">
              Ver exames
            </Link>
          </p>
          <p className="mt-4 text-xs font-medium text-slate-500">Alertas</p>
          <Link to="/alerts" className="text-sm text-teal-700 underline">
            Ver todos os alertas
          </Link>
        </div>
      </div>

      <div className="rounded-xl border border-[var(--color-border-subtle)] bg-white p-4 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-800">Linha do tempo</h3>
        <div className="mt-4 flex flex-wrap gap-4 text-sm">
          <span
            className="cursor-help rounded-full border border-slate-200 bg-slate-50 px-3 py-1"
            title={`Admissão: ${new Date(patient.admittedAt).toLocaleString('pt-BR')}`}
          >
            Admissão
          </span>
          <span
            className="cursor-help rounded-full border border-slate-200 bg-slate-50 px-3 py-1"
            title="Check-in registrado nesta demo"
          >
            Check-in
          </span>
          <span
            className="cursor-help rounded-full border border-slate-200 bg-slate-50 px-3 py-1"
            title={`${patient.exams.length} exames solicitados`}
          >
            Exames solicitados
          </span>
          <span
            className="cursor-help rounded-full border border-slate-200 bg-slate-50 px-3 py-1"
            title="Consulte o painel de alertas"
          >
            Alertas
          </span>
        </div>
      </div>

      <CIDEditModal
        open={cidOpen}
        patient={patient}
        onClose={() => setCidOpen(false)}
        onSaved={() => void refetch()}
      />

      {vitalOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
          <div className="w-full max-w-sm rounded-xl border bg-white p-5 shadow-xl">
            <h4 className="font-semibold text-slate-900">Simular sinal vital</h4>
            <div className="mt-3 space-y-2">
              <select
                value={vField}
                onChange={(e) =>
                  setVField(e.target.value as typeof vField)
                }
                className="w-full rounded border px-2 py-2 text-sm"
              >
                <option value="spo2">SpO₂ (%)</option>
                <option value="temp">Temperatura (°C)</option>
                <option value="hr">FC (bpm)</option>
                <option value="bp">PA (ex: 130/85)</option>
              </select>
              <input
                value={vValue}
                onChange={(e) => setVValue(e.target.value)}
                placeholder="Valor"
                className="w-full rounded border px-2 py-2 text-sm"
              />
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setVitalOpen(false)}
                className="rounded px-3 py-1.5 text-sm text-slate-600"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={() => void applyVitalSimulation()}
                className="rounded bg-teal-600 px-3 py-1.5 text-sm text-white"
              >
                Aplicar
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
