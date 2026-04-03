import { Search } from 'lucide-react';
import { useEffect, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { AgentSpinner } from '@/components/AgentSpinner';
import { createPatientMock, getCidListMock } from '@/api/clinicalApi';
import { useAppSession } from '@/context/AppSessionContext';
import type { Cid, PatientSex } from '@/types/domain';

const COMORBIDITY_OPTIONS = [
  'HAS',
  'DM2',
  'IRC',
  'DPOC',
  'Obesidade',
  'Outras',
];

const SPINNER_MESSAGES = [
  'Registrando paciente…',
  'Consultando protocolo clínico…',
  'Identificando exames recomendados…',
  'Gerando plano inicial…',
];

/** Alinha overlay com duração mínima da demo (doc: 1,5 s): trabalho mock roda em paralelo ao delay. */
const CHECKIN_SPINNER_MS = 1500;

export function CheckInPage() {
  const navigate = useNavigate();
  const {
    setActivePatientId,
    refreshAdmittedPatients,
    refreshAlertBadge,
  } = useAppSession();

  const [cids, setCids] = useState<Cid[]>([]);
  const [cidQuery, setCidQuery] = useState('');
  const [selectedCid, setSelectedCid] = useState<Cid | null>(null);

  const [name, setName] = useState('');
  const [age, setAge] = useState('45');
  const [sex, setSex] = useState<PatientSex>('M');
  const [bed, setBed] = useState('');
  const [chiefComplaint, setChiefComplaint] = useState('');
  const [comorbidities, setComorbidities] = useState<string[]>([]);
  const [medications, setMedications] = useState('');
  const [spinning, setSpinning] = useState(false);

  useEffect(() => {
    void getCidListMock().then(setCids);
  }, []);

  const filteredCids = cids.filter(
    (c) =>
      c.code.toLowerCase().includes(cidQuery.trim().toLowerCase()) ||
      c.label.toLowerCase().includes(cidQuery.trim().toLowerCase()),
  );

  function toggleComorbidity(key: string) {
    setComorbidities((prev) =>
      prev.includes(key) ? prev.filter((x) => x !== key) : [...prev, key],
    );
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!selectedCid || !name.trim() || !bed.trim() || !chiefComplaint.trim()) {
      return;
    }
    const ageNum = Number(age);
    if (Number.isNaN(ageNum) || ageNum < 0 || ageNum > 120) {
      return;
    }
    setSpinning(true);
    const [patient] = await Promise.all([
      createPatientMock({
        name: name.trim(),
        age: ageNum,
        sex,
        bed: bed.trim(),
        cid: selectedCid,
        chiefComplaint: chiefComplaint.trim().slice(0, 300),
        comorbidities,
        currentMedications: medications,
      }),
      new Promise<void>((r) => setTimeout(r, CHECKIN_SPINNER_MS)),
    ]);
    setSpinning(false);
    setActivePatientId(patient.id);
    await refreshAdmittedPatients();
    await refreshAlertBadge();
    navigate('/flow');
  }

  return (
    <div className="mx-auto max-w-[640px]">
      {spinning ? (
        <AgentSpinner messages={SPINNER_MESSAGES} totalMs={CHECKIN_SPINNER_MS} />
      ) : null}
      <div className="rounded-2xl border border-[var(--color-border-subtle)] bg-white p-6 shadow-sm">
        <h2 className="text-xl font-semibold text-slate-900">
          Check-in / Admissão
        </h2>
        <p className="mt-1 text-sm text-slate-600">
          Admita um paciente para iniciar a demo. Dados mock.
        </p>

        <form onSubmit={(e) => void onSubmit(e)} className="mt-6 space-y-4">
          <div>
            <label className="text-sm font-medium text-slate-700">
              Nome completo <span className="text-red-600">*</span>
            </label>
            <input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1 w-full rounded-lg border border-[var(--color-border-subtle)] px-3 py-2 text-sm"
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="text-sm font-medium text-slate-700">
                Idade <span className="text-red-600">*</span>
              </label>
              <input
                required
                type="number"
                min={0}
                max={120}
                value={age}
                onChange={(e) => setAge(e.target.value)}
                className="mt-1 w-full rounded-lg border border-[var(--color-border-subtle)] px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-slate-700">
                Sexo <span className="text-red-600">*</span>
              </label>
              <select
                value={sex}
                onChange={(e) => setSex(e.target.value as PatientSex)}
                className="mt-1 w-full rounded-lg border border-[var(--color-border-subtle)] px-3 py-2 text-sm"
              >
                <option value="M">Masculino</option>
                <option value="F">Feminino</option>
              </select>
            </div>
          </div>
          <div>
            <label className="text-sm font-medium text-slate-700">
              Leito <span className="text-red-600">*</span>
            </label>
            <input
              required
              value={bed}
              onChange={(e) => setBed(e.target.value)}
              placeholder="ex.: UTI-03"
              className="mt-1 w-full rounded-lg border border-[var(--color-border-subtle)] px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="text-sm font-medium text-slate-700">
              CID principal <span className="text-red-600">*</span>
            </label>
            <div className="relative mt-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                type="search"
                value={cidQuery}
                onChange={(e) => setCidQuery(e.target.value)}
                placeholder="Buscar CID…"
                className="w-full rounded-lg border border-[var(--color-border-subtle)] py-2 pl-9 pr-3 text-sm"
              />
            </div>
            <ul className="mt-2 max-h-36 overflow-auto rounded-lg border border-[var(--color-border-subtle)]">
              {filteredCids.slice(0, 12).map((c) => (
                <li key={c.code}>
                  <button
                    type="button"
                    onClick={() => setSelectedCid(c)}
                    className={`flex w-full flex-col items-start px-3 py-2 text-left text-sm hover:bg-teal-50 ${
                      selectedCid?.code === c.code ? 'bg-teal-100' : ''
                    }`}
                  >
                    <span className="font-mono text-xs">{c.code}</span>
                    <span>{c.label}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <label className="text-sm font-medium text-slate-700">
              Queixa principal <span className="text-red-600">*</span>
            </label>
            <textarea
              required
              maxLength={300}
              rows={3}
              value={chiefComplaint}
              onChange={(e) => setChiefComplaint(e.target.value)}
              className="mt-1 w-full rounded-lg border border-[var(--color-border-subtle)] px-3 py-2 text-sm"
            />
            <p className="mt-0.5 text-xs text-slate-500">
              {chiefComplaint.length}/300
            </p>
          </div>
          <fieldset>
            <legend className="text-sm font-medium text-slate-700">
              Comorbidades
            </legend>
            <div className="mt-2 flex flex-wrap gap-3">
              {COMORBIDITY_OPTIONS.map((opt) => (
                <label key={opt} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={comorbidities.includes(opt)}
                    onChange={() => toggleComorbidity(opt)}
                  />
                  {opt}
                </label>
              ))}
            </div>
          </fieldset>
          <div>
            <label className="text-sm font-medium text-slate-700">
              Medicamentos em uso
            </label>
            <textarea
              rows={3}
              value={medications}
              onChange={(e) => setMedications(e.target.value)}
              placeholder="Uma linha por medicamento"
              className="mt-1 w-full rounded-lg border border-[var(--color-border-subtle)] px-3 py-2 text-sm"
            />
          </div>
          <button
            type="submit"
            disabled={!selectedCid || spinning}
            className="w-full rounded-lg bg-teal-600 py-3 text-sm font-semibold text-white hover:bg-teal-700 disabled:opacity-50"
          >
            Admitir paciente
          </button>
        </form>
      </div>
    </div>
  );
}
