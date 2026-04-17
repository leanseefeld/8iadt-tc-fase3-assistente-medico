import {
  createPatientMock,
  getCidListMock,
  getPatientsMock,
  reAdmitPatientMock,
  getComorbidities,
  type ComorbidityOption,
} from '@/api/clinicalApi';
import { useAppSession } from '@/context/AppSessionContext';
import { useToast } from '@/context/ToastContext';
import type { Cid, Patient, PatientSex } from '@/types/domain';
import { Search, UserPlus, UserRoundSearch } from 'lucide-react';
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from 'react';
import { useNavigate } from 'react-router-dom';

type CheckInMode = 'new' | 'return';

export function CheckInPage() {
  const navigate = useNavigate();
  const { showToast } = useToast();
  const {
    setActivePatientId,
    refreshAdmittedPatients,
    refreshAlertBadge,
  } = useAppSession();

  const [mode, setMode] = useState<CheckInMode>('return');

  const [cids, setCids] = useState<Cid[]>([]);
  const [cidQuery, setCidQuery] = useState('');
  const [selectedCid, setSelectedCid] = useState<Cid | null>(null);
  const [cidPickerOpen, setCidPickerOpen] = useState(false);
  const cidPickerRef = useRef<HTMLDivElement>(null);

  const [comorbPickerOpen, setComorbPickerOpen] = useState(false);
  const [comorbQuery, setComorbQuery] = useState('');
  const comorbPickerRef = useRef<HTMLDivElement>(null);

  const [discharged, setDischarged] = useState<Patient[]>([]);
  const [returnQuery, setReturnQuery] = useState('');
  const [selectedReturn, setSelectedReturn] = useState<Patient | null>(null);

  const [name, setName] = useState('');
  const [age, setAge] = useState('');
  const [sex, setSex] = useState<PatientSex>('M');
  const [observations, setChiefComplaint] = useState('');
  const [comorbidities, setComorbidities] = useState<string[]>([]);
  const [comorbidityOptions, setComorbidityOptions] = useState<ComorbidityOption[]>([]);
  const [configLoading, setConfigLoading] = useState(true);
  const [medications, setMedications] = useState('');
  const [spinning, setSpinning] = useState(false);

  useEffect(() => {
    void getCidListMock().then(setCids);
  }, []);

  useEffect(() => {
    void getPatientsMock({ status: 'discharged' }).then(setDischarged);
  }, []);

  // Load comorbidity options from backend
  useEffect(() => {
    setConfigLoading(true);
    void getComorbidities()
      .then((response) => {
        setComorbidityOptions(response.comorbidities);
      })
      .catch((error) => {
        console.error('Failed to load comorbidity options:', error);
        showToast('Erro ao carregar opções de comorbidades');
      })
      .finally(() => {
        setConfigLoading(false);
      });
  }, [showToast]);

  // Fecha lista CID ao clicar fora.
  useEffect(() => {
    if (!cidPickerOpen) {
      return;
    }
    function handleMouseDown(e: MouseEvent) {
      if (
        cidPickerRef.current &&
        !cidPickerRef.current.contains(e.target as Node)
      ) {
        setCidPickerOpen(false);
      }
    }
    document.addEventListener('mousedown', handleMouseDown);
    return () => document.removeEventListener('mousedown', handleMouseDown);
  }, [cidPickerOpen]);

  // Fecha lista comorbidades ao clicar fora.
  useEffect(() => {
    if (!comorbPickerOpen) {
      return;
    }
    function handleMouseDown(e: MouseEvent) {
      if (
        comorbPickerRef.current &&
        !comorbPickerRef.current.contains(e.target as Node)
      ) {
        setComorbPickerOpen(false);
      }
    }
    document.addEventListener('mousedown', handleMouseDown);
    return () => document.removeEventListener('mousedown', handleMouseDown);
  }, [comorbPickerOpen]);

  const filteredCids = cids.filter(
    (c) =>
      c.code.toLowerCase().includes(cidQuery.trim().toLowerCase()) ||
      c.label.toLowerCase().includes(cidQuery.trim().toLowerCase()),
  );

  const filteredReturn = useMemo(() => {
    const q = returnQuery.trim().toLowerCase();
    if (!q) {
      return discharged;
    }
    return discharged.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        p.id.toLowerCase().includes(q) ||
        p.cid.code.toLowerCase().includes(q),
    );
  }, [discharged, returnQuery]);

  const filteredComorbOptions = useMemo(() => {
    const q = comorbQuery.trim().toLowerCase();
    if (!q) {
      return comorbidityOptions;
    }
    return comorbidityOptions.filter(
      (o) =>
        o.code.toLowerCase().includes(q) || o.label.toLowerCase().includes(q),
    );
  }, [comorbQuery, comorbidityOptions]);

  const comorbidityCodeToLabel = useMemo(() => {
    const map: Record<string, string> = {};
    comorbidityOptions.forEach((opt) => {
      map[opt.code] = opt.label;
    });
    return map;
  }, [comorbidityOptions]);

  function toggleComorbidity(key: string) {
    setComorbidities((prev) =>
      prev.includes(key) ? prev.filter((x) => x !== key) : [...prev, key],
    );
  }

  function switchMode(next: CheckInMode) {
    setMode(next);
    if (next === 'new') {
      setSelectedReturn(null);
      setReturnQuery('');
    } else {
      setSelectedCid(null);
      setCidQuery('');
      setCidPickerOpen(false);
      setComorbQuery('');
      setComorbPickerOpen(false);
      setName('');
      setAge('');
      setChiefComplaint('');
      setComorbidities([]);
      setMedications('');
    }
  }

  function openCidPicker() {
    setCidPickerOpen(true);
    setCidQuery('');
  }

  function openComorbPicker() {
    setComorbPickerOpen(true);
    setComorbQuery('');
  }

  async function runReadmit() {
    if (!selectedReturn) {
      return;
    }
    setSpinning(true);
    try {
      const patient = await reAdmitPatientMock(selectedReturn.id);
      if (!patient) {
        showToast('Não foi possível readmitir este registro.');
        return;
      }
      setActivePatientId(patient.id);
      await refreshAdmittedPatients();
      await refreshAlertBadge();
      navigate('/');
    } finally {
      setSpinning(false);
    }
  }

  async function onSubmitNew(e: FormEvent) {
    e.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) {
      showToast('Indique o nome completo.');
      return;
    }
    const ageNum = Number(age);
    if (age.trim() === '' || Number.isNaN(ageNum) || ageNum < 0 || ageNum > 120) {
      showToast('Indique a idade (0–120).');
      return;
    }

    const cid = selectedCid ?? cids[0];
    if (!cid) {
      showToast('Lista de CIDs ainda não carregou. Aguarde um instante.');
      return;
    }

    setSpinning(true);
    try {
      const patient = await createPatientMock({
        name: trimmedName,
        age: ageNum,
        sex,
        cid,
        observations: observations.trim() || undefined,
        comorbidities,
        currentMedications: medications,
      });
      setActivePatientId(patient.id);
      await refreshAdmittedPatients();
      await refreshAlertBadge();
      navigate('/');
    } finally {
      setSpinning(false);
    }
  }

  return (
    <div className="mx-auto max-w-[640px]">
      <div className="rounded-2xl border border-[var(--color-border-subtle)] bg-white p-6 shadow-sm">
        <h2 className="text-xl font-semibold text-slate-900">
          Check-in / Admissão
        </h2>
        <p className="mt-1 text-sm text-slate-600">
          Por padrão: readmissão de quem já teve alta. Para estreante, use o
          botão grande abaixo.
        </p>

        {mode === 'return' ? (
          <div className="mt-6 space-y-4">
            <section className="rounded-xl border border-teal-100 bg-teal-50/50 p-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-teal-900">
                <UserRoundSearch className="h-4 w-4" />
                Paciente com alta — localizar
              </div>
              <p className="mt-1 text-xs text-slate-600">
                Pesquise por nome, ID ou CID e selecione. Resumo é só leitura.
              </p>
              <input
                type="search"
                value={returnQuery}
                onChange={(e) => setReturnQuery(e.target.value)}
                placeholder="Buscar…"
                className="mt-2 w-full rounded-lg border border-[var(--color-border-subtle)] px-3 py-2 text-sm"
              />
              <ul className="mt-2 max-h-48 overflow-auto rounded-lg border border-[var(--color-border-subtle)] bg-white">
                {filteredReturn.length === 0 ? (
                  <li className="px-3 py-2 text-sm text-slate-500">
                    Nenhum registro com alta correspondente.
                  </li>
                ) : (
                  filteredReturn.map((p) => (
                    <li key={p.id}>
                      <button
                        type="button"
                        onClick={() => setSelectedReturn(p)}
                        className={`flex w-full flex-col items-start px-3 py-2 text-left text-sm hover:bg-teal-50 ${
                          selectedReturn?.id === p.id ? 'bg-teal-100' : ''
                        }`}
                      >
                        <span className="font-medium text-slate-900">
                          {p.name}
                        </span>
                        <span className="text-xs text-slate-600">
                          {p.cid.code} · {p.cid.label}
                        </span>
                        <span className="font-mono text-[10px] text-slate-400">
                          {p.id}
                        </span>
                      </button>
                    </li>
                  ))
                )}
              </ul>
            </section>

            {selectedReturn ? (
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                <h3 className="text-sm font-semibold text-slate-800">
                  Resumo (não editável)
                </h3>
                <dl className="mt-3 space-y-2 text-sm">
                  <div className="flex justify-between gap-4">
                    <dt className="text-slate-500">Nome</dt>
                    <dd className="text-right font-medium text-slate-900">
                      {selectedReturn.name}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-slate-500">Idade / sexo</dt>
                    <dd className="text-right text-slate-800">
                      {selectedReturn.age} ·{' '}
                      {selectedReturn.sex === 'M' ? 'Masc.' : 'Fem.'}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-slate-500">CID</dt>
                    <dd className="text-right text-slate-800">
                      {selectedReturn.cid.code} — {selectedReturn.cid.label}
                    </dd>
                  </div>
                  <div className="border-t border-slate-200 pt-2">
                    <dt className="text-slate-500">Queixa (histórico)</dt>
                    <dd className="mt-1 text-slate-800">
                      {selectedReturn.observations}
                    </dd>
                  </div>
                </dl>
                <button
                  type="button"
                  onClick={() => void runReadmit()}
                  disabled={spinning}
                  className="mt-4 w-full rounded-lg bg-teal-600 py-3 text-sm font-semibold text-white hover:bg-teal-700 disabled:opacity-50"
                >
                  Confirmar readmissão
                </button>
              </div>
            ) : (
              <p className="text-center text-sm text-slate-500">
                Selecione um paciente na lista para ver o resumo e confirmar.
              </p>
            )}

            <button
              type="button"
              onClick={() => switchMode('new')}
              className="flex w-full items-center justify-center gap-3 rounded-2xl border-2 border-dashed border-teal-400 bg-gradient-to-b from-teal-50 to-white px-5 py-5 text-base font-semibold text-teal-900 shadow-sm transition hover:border-teal-500 hover:from-teal-100/80 hover:shadow-md"
            >
              <UserPlus className="h-7 w-7 shrink-0" aria-hidden />
              <span className="text-left leading-tight">
                Novo paciente
                <span className="mt-0.5 block text-sm font-normal text-slate-600">
                  Admissão de paciente que ainda não consta com alta
                </span>
              </span>
            </button>
          </div>
        ) : (
          <form
            onSubmit={(e) => void onSubmitNew(e)}
            className="mt-6 space-y-4"
          >
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <h3 className="text-sm font-semibold text-slate-800">
                Nova admissão
              </h3>
              <button
                type="button"
                onClick={() => switchMode('return')}
                className="text-sm font-medium text-teal-800 underline hover:text-teal-950"
              >
                ← Voltar a readmissão
              </button>
            </div>
            <p className="text-xs text-slate-600">
              <span className="text-red-600">*</span> Nome e idade obrigatórios.
              Outros campos opcionais (predefinições mock se vazios).
            </p>

            <div>
              <label className="text-sm font-medium text-slate-700">
                Nome completo <span className="text-red-600">*</span>
              </label>
              <input
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoComplete="name"
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
                  Sexo
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
            <div ref={cidPickerRef} className="relative">
              <label className="text-sm font-medium text-slate-700">
                CID principal
              </label>
              <button
                type="button"
                onClick={openCidPicker}
                className="mt-1 flex w-full items-center gap-2 rounded-lg border border-[var(--color-border-subtle)] bg-white px-3 py-2.5 text-left text-sm text-slate-800 hover:bg-slate-50"
              >
                <Search className="h-4 w-4 shrink-0 text-slate-400" />
                <span className="min-w-0 flex-1 truncate">
                  {selectedCid
                    ? `${selectedCid.code} — ${selectedCid.label}`
                    : 'Clique para abrir a lista e escolher'}
                </span>
              </button>
              {cidPickerOpen ? (
                <div className="absolute left-0 right-0 z-20 mt-1 rounded-lg border border-[var(--color-border-subtle)] bg-white shadow-lg">
                  <input
                    type="search"
                    autoFocus
                    value={cidQuery}
                    onChange={(e) => setCidQuery(e.target.value)}
                    placeholder="Filtrar por código ou descrição…"
                    className="w-full rounded-t-lg border-b border-[var(--color-border-subtle)] px-3 py-2 text-sm"
                  />
                  <ul className="max-h-40 overflow-auto rounded-b-lg">
                    {filteredCids.slice(0, 20).map((c) => (
                      <li key={c.code}>
                        <button
                          type="button"
                          onClick={() => {
                            setSelectedCid(c);
                            setCidPickerOpen(false);
                            setCidQuery('');
                          }}
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
              ) : null}
              <p className="mt-1 text-xs text-slate-500">
                Sem escolha no envio, usa o primeiro CID da lista.
              </p>
            </div>

            <div>
              <label className="text-sm font-medium text-slate-700">
                Observações:
              </label>
              <textarea
                maxLength={300}
                rows={3}
                value={observations}
                onChange={(e) => setChiefComplaint(e.target.value)}
                placeholder="Escreva uma observação"
                className="mt-1 w-full rounded-lg border border-[var(--color-border-subtle)] px-3 py-2 text-sm"
              />
              <p className="mt-0.5 text-xs text-slate-500">
                {observations.length}/300
              </p>
            </div>
            <div ref={comorbPickerRef} className="relative">
              <label className="text-sm font-medium text-slate-700">
                Comorbidades{configLoading && <span className="ml-1 text-slate-400">…</span>}
              </label>
              <button
                type="button"
                onClick={openComorbPicker}
                disabled={configLoading}
                className="mt-1 flex w-full items-center gap-2 rounded-lg border border-[var(--color-border-subtle)] bg-white px-3 py-2.5 text-left text-sm text-slate-800 hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Search className="h-4 w-4 shrink-0 text-slate-400" />
                <span className="min-w-0 flex-1 truncate">
                  {comorbidities.length === 0
                    ? 'Clique para abrir a lista e escolher (várias)'
                    : `${comorbidities.length} selecionada(s) — clique para alterar`}
                </span>
              </button>
              {comorbidities.length > 0 ? (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {comorbidities.map((c) => (
                    <span
                      key={c}
                      className="rounded-full bg-teal-100 px-2.5 py-0.5 text-xs font-medium text-teal-900"
                    >
                      {comorbidityCodeToLabel[c] || c}
                    </span>
                  ))}
                </div>
              ) : null}
              {comorbPickerOpen ? (
                <div className="absolute left-0 right-0 z-[21] mt-1 rounded-lg border border-[var(--color-border-subtle)] bg-white shadow-lg">
                  <input
                    type="search"
                    autoFocus
                    value={comorbQuery}
                    onChange={(e) => setComorbQuery(e.target.value)}
                    placeholder="Filtrar comorbidades…"
                    className="w-full rounded-t-lg border-b border-[var(--color-border-subtle)] px-3 py-2 text-sm"
                  />
                  <ul className="max-h-44 overflow-auto rounded-b-lg py-1">
                    {filteredComorbOptions.length === 0 ? (
                      <li className="px-3 py-2 text-sm text-slate-500">
                        Nenhum resultado.
                      </li>
                    ) : (
                      filteredComorbOptions.map((opt) => {
                        const on = comorbidities.includes(opt.code);
                        return (
                          <li key={opt.code}>
                            <button
                              type="button"
                              onClick={() => toggleComorbidity(opt.code)}
                              className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-teal-50 ${
                                on ? 'bg-teal-50 font-medium text-teal-900' : ''
                              }`}
                            >
                              <span
                                className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border text-[10px] ${
                                  on
                                    ? 'border-teal-600 bg-teal-600 text-white'
                                    : 'border-slate-300 bg-white'
                                }`}
                                aria-hidden
                              >
                                {on ? '✓' : ''}
                              </span>
                              {opt.label}
                            </button>
                          </li>
                        );
                      })
                    )}
                  </ul>
                  <p className="border-t border-[var(--color-border-subtle)] px-3 py-2 text-xs text-slate-500">
                    Clique numa linha para marcar ou desmarcar. Clique fora para
                    fechar.
                  </p>
                </div>
              ) : null}
            </div>
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
              disabled={spinning}
              className="w-full rounded-lg bg-teal-600 py-3 text-sm font-semibold text-white hover:bg-teal-700 disabled:opacity-50"
            >
              Admitir paciente
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
