import { useCallback, useEffect, useMemo, useState } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import {
  archivePrescriptionMock,
  createPrescriptionMock,
  getMedicationCatalogMock,
  getPrescriptionsMock,
} from '@/api/clinicalApi';
import {
  PRESCRIPTION_CONCENTRATION_PRESETS,
  PRESCRIPTION_CUSTOM_KEY,
  PRESCRIPTION_FORM_PRESETS,
} from '@/mocks/internal/prescriptionFieldOptions';
import { useAppSession } from '@/context/AppSessionContext';
import { useToast } from '@/context/ToastContext';
import { usePatientDetail } from '@/hooks/usePatientDetail';
import type { MedicationOption } from '@/types/domain';
import type { PrescriberKind, Prescription } from '@/types/prescription';
import './PrescriptionsPage.print.css';

type FormRow = {
  /** Vazio = placeholder; __custom__ = Personalizado; caso contrário código do catálogo RENAME. */
  medicationCode: string;
  medicationName: string;
  concentrationKey: string;
  concentration: string;
  pharmaceuticalFormKey: string;
  pharmaceuticalForm: string;
  quantity: string;
  posology: string;
};

type PrescriptionsLocationState = {
  fromSuggestion?: { description: string };
} | null;

function emptyRow(): FormRow {
  return {
    medicationCode: '',
    medicationName: '',
    concentrationKey: '',
    concentration: '',
    pharmaceuticalFormKey: '',
    pharmaceuticalForm: '',
    quantity: '',
    posology: '',
  };
}

function formatDt(iso: string): string {
  try {
    return new Intl.DateTimeFormat('pt-BR', {
      dateStyle: 'short',
      timeStyle: 'short',
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

/** Nome exibido do prescritor (legado pode ter rótulos antigos substituídos). */
function prescriptionPrescriberDisplayName(rx: Prescription): string {
  const n = rx.prescriberName.trim();
  if (n === 'Assistente Médico IA') {
    return 'Médico responsável';
  }
  return rx.prescriberName;
}

/** Documento visual no estilo Receita de Controle Especial (conteúdo educativo / demo). */
function RceViewer({
  rx,
  patientDisplayName,
}: {
  rx: Prescription;
  patientDisplayName: string;
}) {
  const prescriberLabel = prescriptionPrescriberDisplayName(rx);

  return (
    <div
      id="prescription-print-surface"
      className="prescriptions-print-root rounded-xl border border-slate-300 bg-white p-6 shadow-inner print:border-0 print:shadow-none"
    >
      <div className="border-b-2 border-slate-800 pb-2 text-center">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-600">
          Ministério da Saúde / ANVISA — modelo educativo
        </p>
        <h2 className="mt-1 text-lg font-bold text-slate-900">
          RECEITA DE CONTROLE ESPECIAL
        </h2>
        <p className="mt-1 text-xs text-slate-600">
          Reprodução simplificada para o protótipo; valide sempre o modelo vigente.
        </p>
      </div>

      <div className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
        <section>
          <h3 className="text-xs font-bold uppercase text-slate-600">
            Paciente
          </h3>
          <p className="mt-1 font-medium text-slate-900">{patientDisplayName}</p>
          {rx.patientCpf ? (
            <p className="text-slate-700">CPF: {rx.patientCpf}</p>
          ) : (
            <p className="text-slate-500">CPF não informado</p>
          )}
        </section>
        <section>
          <h3 className="text-xs font-bold uppercase text-slate-600">
            Identificação da prescrição
          </h3>
          <p className="mt-1 text-slate-700">Emitida em: {formatDt(rx.issuedAt)}</p>
          <p className="break-all text-xs text-slate-500">ID: {rx.id}</p>
        </section>
      </div>

      <section className="mt-4 text-sm">
        <h3 className="text-xs font-bold uppercase text-slate-600">
          Prescritor
        </h3>
        <p className="mt-1 font-medium text-slate-900">{prescriberLabel}</p>
        {rx.prescriberCrm && rx.prescriberCrmUf ? (
          <p className="text-slate-700">
            CRM {rx.prescriberCrm} / {rx.prescriberCrmUf}
          </p>
        ) : null}
        {rx.institutionName ? (
          <p className="mt-1 text-slate-700">{rx.institutionName}</p>
        ) : null}
        {rx.institutionCnpjCnes ? (
          <p className="text-slate-700">CNPJ / CNES: {rx.institutionCnpjCnes}</p>
        ) : null}
        {rx.institutionAddress ? (
          <p className="text-slate-700">{rx.institutionAddress}</p>
        ) : null}
        {rx.institutionPhone ? (
          <p className="text-slate-700">Tel.: {rx.institutionPhone}</p>
        ) : null}
      </section>

      <section className="mt-4">
        <h3 className="text-xs font-bold uppercase text-slate-600">
          Medicamentos e posologia
        </h3>
        <table className="mt-2 w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-slate-400 text-left text-xs uppercase text-slate-600">
              <th className="py-2 pr-2">Medicamento</th>
              <th className="py-2 pr-2">Forma / Qtd.</th>
              <th className="py-2">Posologia</th>
            </tr>
          </thead>
          <tbody>
            {rx.items.map((it, i) => (
              <tr key={i} className="border-b border-slate-200 align-top">
                <td className="py-2 pr-2">
                  <span className="font-medium text-slate-900">
                    {it.medicationName}
                  </span>
                  {it.concentration ? (
                    <span className="block text-slate-600">{it.concentration}</span>
                  ) : null}
                </td>
                <td className="py-2 pr-2 text-slate-700">
                  {[it.pharmaceuticalForm, it.quantity].filter(Boolean).join(' · ') ||
                    '—'}
                </td>
                <td className="py-2 text-slate-700">
                  {it.posology?.trim() || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {rx.notes?.trim() ? (
        <section className="mt-4 text-sm">
          <h3 className="text-xs font-bold uppercase text-slate-600">
            Observações
          </h3>
          <p className="mt-1 whitespace-pre-wrap text-slate-800">{rx.notes}</p>
        </section>
      ) : null}

      <div className="mt-10 border-t border-slate-300 pt-4 text-sm">
        <p className="text-slate-700">Assinatura e carimbo do prescritor</p>
        <div className="mt-8 h-px w-64 bg-slate-400" />
        <p className="mt-1 text-slate-600">{prescriberLabel}</p>
      </div>
    </div>
  );
}

export function PrescriptionsPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { showToast } = useToast();
  const { admittedPatients, activePatientId, activeDoctor } = useAppSession();
  const { patient } = usePatientDetail(activePatientId);

  const [tab, setTab] = useState<'active' | 'archived'>('active');
  const [all, setAll] = useState<Prescription[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<Prescription | null>(null);
  const [showForm, setShowForm] = useState(false);

  const [patientCpf, setPatientCpf] = useState('');
  const [prescriberKind, setPrescriberKind] =
    useState<PrescriberKind>('doctor');
  const [prescriberName, setPrescriberName] = useState('');
  const [prescriberCrm, setPrescriberCrm] = useState('');
  const [prescriberUf, setPrescriberUf] = useState('');
  const [institutionName, setInstitutionName] = useState('');
  const [institutionCnpjCnes, setInstitutionCnpjCnes] = useState('');
  const [institutionAddress, setInstitutionAddress] = useState('');
  const [institutionPhone, setInstitutionPhone] = useState('');
  const [notes, setNotes] = useState('');
  const [rows, setRows] = useState<FormRow[]>([emptyRow()]);

  const [medicationCatalog, setMedicationCatalog] = useState<MedicationOption[]>(
    [],
  );

  const [archiveOpen, setArchiveOpen] = useState(false);
  const [archiveReason, setArchiveReason] = useState('');
  const [archiveBusy, setArchiveBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void getMedicationCatalogMock()
      .then((list) => {
        if (!cancelled) {
          setMedicationCatalog(list);
        }
      })
      .catch((err) => {
        console.error(err);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const sortedMedications = useMemo(
    () =>
      [...medicationCatalog].sort((a, b) =>
        a.label.localeCompare(b.label, 'pt-BR'),
      ),
    [medicationCatalog],
  );

  const load = useCallback(async () => {
    if (!activePatientId) {
      return;
    }
    setLoading(true);
    try {
      const list = await getPrescriptionsMock(activePatientId, true);
      setAll(list);
    } catch (e) {
      console.error(e);
      showToast('Não foi possível carregar as prescrições.');
    } finally {
      setLoading(false);
    }
  }, [activePatientId, showToast]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!showForm || prescriberKind !== 'doctor' || !activeDoctor) {
      return;
    }
    setPrescriberName(activeDoctor.name);
    setPrescriberCrm(activeDoctor.crm);
    setPrescriberUf(activeDoctor.uf);
  }, [activeDoctor, showForm, prescriberKind]);

  const activeList = useMemo(
    () => all.filter((p) => !p.archivedAt),
    [all],
  );
  const archivedList = useMemo(
    () => all.filter((p) => p.archivedAt),
    [all],
  );

  const displayed = tab === 'active' ? activeList : archivedList;

  useEffect(() => {
    const st = location.state as PrescriptionsLocationState;
    const desc = st?.fromSuggestion?.description?.trim();
    if (!desc) {
      return;
    }
    setShowForm(true);
    setSelected(null);
    setPrescriberKind('doctor');
    if (activeDoctor) {
      setPrescriberName(activeDoctor.name);
      setPrescriberCrm(activeDoctor.crm);
      setPrescriberUf(activeDoctor.uf);
    }
    setRows([
      {
        ...emptyRow(),
        medicationCode: PRESCRIPTION_CUSTOM_KEY,
        medicationName: desc,
      },
    ]);
    navigate(location.pathname, { replace: true, state: {} });
  }, [activeDoctor, location, location.pathname, location.state, navigate]);

  function resetFormFromDoctor() {
    if (!activeDoctor) {
      return;
    }
    setPrescriberKind('doctor');
    setPrescriberName(activeDoctor.name);
    setPrescriberCrm(activeDoctor.crm);
    setPrescriberUf(activeDoctor.uf);
    setRows([emptyRow()]);
    setNotes('');
    setPatientCpf('');
    setInstitutionName('');
    setInstitutionCnpjCnes('');
    setInstitutionAddress('');
    setInstitutionPhone('');
  }

  function openNewForm() {
    resetFormFromDoctor();
    setShowForm(true);
    setSelected(null);
  }

  async function submitForm() {
    if (!activePatientId || !activeDoctor) {
      return;
    }
    const byCode = new Map(
      medicationCatalog.map((m) => [m.code, m] as const),
    );
    const items = rows
      .map((r) => {
        const medicationName =
          !r.medicationCode
            ? ''
            : r.medicationCode === PRESCRIPTION_CUSTOM_KEY
              ? r.medicationName.trim()
              : (byCode.get(r.medicationCode)?.label ??
                r.medicationName.trim());
        const concentrationRaw =
          !r.concentrationKey
            ? ''
            : r.concentrationKey === PRESCRIPTION_CUSTOM_KEY
              ? r.concentration
              : (PRESCRIPTION_CONCENTRATION_PRESETS.find(
                  (p) => p.id === r.concentrationKey,
                )?.label ?? r.concentration);
        const formRaw =
          !r.pharmaceuticalFormKey
            ? ''
            : r.pharmaceuticalFormKey === PRESCRIPTION_CUSTOM_KEY
              ? r.pharmaceuticalForm
              : (PRESCRIPTION_FORM_PRESETS.find(
                  (p) => p.id === r.pharmaceuticalFormKey,
                )?.label ?? r.pharmaceuticalForm);
        return {
          medicationName,
          concentration: concentrationRaw.trim() || undefined,
          pharmaceuticalForm: formRaw.trim() || undefined,
          quantity: r.quantity.trim() || undefined,
          posology: r.posology.trim() || undefined,
        };
      })
      .filter((r) => r.medicationName.length > 0);

    if (items.length === 0) {
      showToast('Inclua ao menos um medicamento com nome preenchido.');
      return;
    }

    try {
      const created = await createPrescriptionMock(activePatientId, {
        patientCpf: patientCpf.trim() || undefined,
        prescriberKind,
        prescriberName: prescriberName.trim(),
        prescriberCrm:
          prescriberKind === 'doctor'
            ? prescriberCrm.trim()
            : prescriberCrm.trim() || undefined,
        prescriberCrmUf:
          prescriberKind === 'doctor'
            ? prescriberUf.trim()
            : prescriberUf.trim() || undefined,
        institutionName: institutionName.trim() || undefined,
        institutionCnpjCnes: institutionCnpjCnes.trim() || undefined,
        institutionAddress: institutionAddress.trim() || undefined,
        institutionPhone: institutionPhone.trim() || undefined,
        items,
        notes: notes.trim() || undefined,
      });
      showToast('Prescrição emitida.');
      setShowForm(false);
      await load();
      setSelected(created);
    } catch (e) {
      console.error(e);
      showToast('Falha ao emitir prescrição. Verifique os dados (ex.: CRM para médico).');
    }
  }

  async function confirmArchive() {
    if (!selected || !activeDoctor || archiveReason.trim().length < 5) {
      return;
    }
    setArchiveBusy(true);
    try {
      await archivePrescriptionMock(
        selected.id,
        archiveReason.trim(),
        activeDoctor.name,
      );
      showToast('Prescrição arquivada.');
      setArchiveOpen(false);
      setArchiveReason('');
      setSelected(null);
      await load();
    } catch (e) {
      console.error(e);
      showToast('Não foi possível arquivar.');
    } finally {
      setArchiveBusy(false);
    }
  }

  if (admittedPatients.length === 0) {
    return <Navigate to="/checkin" replace />;
  }

  if (!activePatientId || !patient) {
    return (
      <p className="text-slate-600">Selecione um paciente admitido.</p>
    );
  }

  // --- UI principal: lista + detalhe / formulário
  return (
    <div className="flex flex-col gap-4 xl:flex-row xl:items-start">
      <div className="prescriptions-no-print min-w-0 flex-1 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-xl font-semibold text-slate-900">Prescrições</h2>
          <button
            type="button"
            onClick={() => openNewForm()}
            disabled={!activeDoctor}
            className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-50"
          >
            Nova prescrição
          </button>
        </div>

        <div className="flex gap-2">
          {(['active', 'archived'] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={`rounded-full px-3 py-1 text-xs font-medium ${
                tab === t
                  ? 'bg-teal-600 text-white'
                  : 'bg-slate-100 text-slate-700'
              }`}
            >
              {t === 'active' ? 'Ativas' : 'Arquivadas'} (
              {t === 'active' ? activeList.length : archivedList.length})
            </button>
          ))}
        </div>

        {loading ? (
          <p className="text-sm text-slate-600">Carregando…</p>
        ) : displayed.length === 0 ? (
          <p className="text-sm text-slate-600">
            Nenhuma prescrição nesta aba.
          </p>
        ) : (
          <ul className="space-y-2">
            {displayed.map((rx) => (
              <li key={rx.id}>
                <button
                  type="button"
                  onClick={() => {
                    setSelected(rx);
                    setShowForm(false);
                  }}
                  className={`w-full rounded-xl border px-4 py-3 text-left text-sm transition-colors ${
                    selected?.id === rx.id
                      ? 'border-teal-500 bg-teal-50'
                      : 'border-[var(--color-border-subtle)] bg-white hover:bg-slate-50'
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium text-slate-900">
                      {formatDt(rx.issuedAt)}
                    </span>
                  </div>
                  <p className="mt-1 text-slate-700">
                    {prescriptionPrescriberDisplayName(rx)} —{' '}
                    {rx.items[0]?.medicationName ?? 'sem itens'}
                    {rx.items.length > 1
                      ? ` (+${rx.items.length - 1})`
                      : ''}
                  </p>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="min-w-0 flex-[1.2] space-y-3">
        {showForm ? (
          <div className="prescriptions-no-print rounded-xl border border-[var(--color-border-subtle)] bg-white p-5 shadow-sm">
            <h3 className="text-lg font-semibold text-slate-900">
              Emitir prescrição
            </h3>
            <form
              className="contents"
              onSubmit={(e) => {
                e.preventDefault();
                void submitForm();
              }}
            >
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div className="sm:col-span-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-800">
                <span className="font-medium text-slate-700">Prescritor: </span>
                {activeDoctor
                  ? `${activeDoctor.name} — CRM ${activeDoctor.crm}/${activeDoctor.uf}`
                  : '—'}
              </div>
              <label className="flex flex-col gap-1 text-sm sm:col-span-2">
                <span className="text-slate-600">CPF do paciente (opcional)</span>
                <input
                  value={patientCpf}
                  onChange={(e) => setPatientCpf(e.target.value)}
                  className="rounded-lg border px-2 py-2"
                  placeholder="000.000.000-00"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm sm:col-span-2">
                <span className="text-slate-600">Instituição (opcional)</span>
                <input
                  name="prescription-institution-name"
                  autoComplete="organization"
                  value={institutionName}
                  onChange={(e) => setInstitutionName(e.target.value)}
                  className="rounded-lg border px-2 py-2"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm sm:col-span-2">
                <span className="text-slate-600">CNPJ ou CNES (opcional)</span>
                <input
                  value={institutionCnpjCnes}
                  onChange={(e) => setInstitutionCnpjCnes(e.target.value)}
                  className="rounded-lg border px-2 py-2"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm sm:col-span-2">
                <span className="text-slate-600">Endereço da instituição</span>
                <input
                  name="prescription-institution-address"
                  autoComplete="street-address"
                  value={institutionAddress}
                  onChange={(e) => setInstitutionAddress(e.target.value)}
                  className="rounded-lg border px-2 py-2"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm sm:col-span-2">
                <span className="text-slate-600">Telefone</span>
                <input
                  type="tel"
                  name="prescription-institution-tel"
                  autoComplete="tel"
                  value={institutionPhone}
                  onChange={(e) => setInstitutionPhone(e.target.value)}
                  className="rounded-lg border px-2 py-2"
                />
              </label>
            </div>

            <div className="mt-6 space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-semibold text-slate-800">
                  Itens da prescrição
                </h4>
                <button
                  type="button"
                  onClick={() => setRows((r) => [...r, emptyRow()])}
                  className="text-xs font-medium text-teal-700 underline"
                >
                  + linha
                </button>
              </div>
              {rows.map((row, idx) => (
                <div
                  key={idx}
                  className="grid gap-2 rounded-lg border border-slate-200 p-3 sm:grid-cols-2"
                >
                  <label className="flex flex-col gap-1 text-sm sm:col-span-2">
                    <span className="text-slate-600">Medicamento *</span>
                    <select
                      value={row.medicationCode}
                      onChange={(e) => {
                        const code = e.target.value;
                        setRows((prev) =>
                          prev.map((x, i) => {
                            if (i !== idx) {
                              return x;
                            }
                            if (code === '') {
                              return {
                                ...x,
                                medicationCode: '',
                                medicationName: '',
                              };
                            }
                            if (code === PRESCRIPTION_CUSTOM_KEY) {
                              return {
                                ...x,
                                medicationCode: PRESCRIPTION_CUSTOM_KEY,
                                medicationName: '',
                              };
                            }
                            const opt = sortedMedications.find(
                              (m) => m.code === code,
                            );
                            return {
                              ...x,
                              medicationCode: code,
                              medicationName: opt?.label ?? '',
                            };
                          }),
                        );
                      }}
                      className="rounded-lg border px-2 py-2 text-slate-800"
                    >
                      <option value="" disabled>
                        Selecione
                      </option>
                      <option value={PRESCRIPTION_CUSTOM_KEY}>
                        Personalizado
                      </option>
                      {sortedMedications.map((m) => (
                        <option key={m.code} value={m.code}>
                          {m.label}
                        </option>
                      ))}
                    </select>
                    {row.medicationCode === PRESCRIPTION_CUSTOM_KEY ? (
                      <input
                        value={row.medicationName}
                        onChange={(e) => {
                          const v = e.target.value;
                          setRows((prev) =>
                            prev.map((x, i) =>
                              i === idx ? { ...x, medicationName: v } : x,
                            ),
                          );
                        }}
                        placeholder="Digite o medicamento (texto livre)"
                        className="rounded-lg border px-2 py-2"
                      />
                    ) : null}
                    {sortedMedications.length === 0 ? (
                      <p className="text-xs text-slate-500">
                        Carregando catálogo de medicamentos…
                      </p>
                    ) : null}
                  </label>
                  <label className="flex flex-col gap-1 text-sm">
                    <span className="text-slate-600">Concentração</span>
                    <select
                      value={row.concentrationKey}
                      onChange={(e) => {
                        const key = e.target.value;
                        setRows((prev) =>
                          prev.map((x, i) => {
                            if (i !== idx) {
                              return x;
                            }
                            if (key === '') {
                              return {
                                ...x,
                                concentrationKey: '',
                                concentration: '',
                              };
                            }
                            if (key === PRESCRIPTION_CUSTOM_KEY) {
                              return {
                                ...x,
                                concentrationKey: key,
                                concentration: '',
                              };
                            }
                            const opt = PRESCRIPTION_CONCENTRATION_PRESETS.find(
                              (p) => p.id === key,
                            );
                            return {
                              ...x,
                              concentrationKey: key,
                              concentration: opt?.label ?? '',
                            };
                          }),
                        );
                      }}
                      className="rounded-lg border px-2 py-2 text-slate-800"
                    >
                      <option value="" disabled>
                        Selecione
                      </option>
                      <option value={PRESCRIPTION_CUSTOM_KEY}>
                        Personalizado
                      </option>
                      {PRESCRIPTION_CONCENTRATION_PRESETS.map((o) => (
                        <option key={o.id} value={o.id}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                    {row.concentrationKey === PRESCRIPTION_CUSTOM_KEY ? (
                      <input
                        value={row.concentration}
                        onChange={(e) => {
                          const v = e.target.value;
                          setRows((prev) =>
                            prev.map((x, i) =>
                              i === idx ? { ...x, concentration: v } : x,
                            ),
                          );
                        }}
                        placeholder="Ex.: 250 mg, 10 UI/ml"
                        className="rounded-lg border px-2 py-2"
                      />
                    ) : null}
                  </label>
                  <label className="flex flex-col gap-1 text-sm">
                    <span className="text-slate-600">Forma farmacêutica</span>
                    <select
                      value={row.pharmaceuticalFormKey}
                      onChange={(e) => {
                        const key = e.target.value;
                        setRows((prev) =>
                          prev.map((x, i) => {
                            if (i !== idx) {
                              return x;
                            }
                            if (key === '') {
                              return {
                                ...x,
                                pharmaceuticalFormKey: '',
                                pharmaceuticalForm: '',
                              };
                            }
                            if (key === PRESCRIPTION_CUSTOM_KEY) {
                              return {
                                ...x,
                                pharmaceuticalFormKey: key,
                                pharmaceuticalForm: '',
                              };
                            }
                            const opt = PRESCRIPTION_FORM_PRESETS.find(
                              (p) => p.id === key,
                            );
                            return {
                              ...x,
                              pharmaceuticalFormKey: key,
                              pharmaceuticalForm: opt?.label ?? '',
                            };
                          }),
                        );
                      }}
                      className="rounded-lg border px-2 py-2 text-slate-800"
                    >
                      <option value="" disabled>
                        Selecione
                      </option>
                      <option value={PRESCRIPTION_CUSTOM_KEY}>
                        Personalizado
                      </option>
                      {PRESCRIPTION_FORM_PRESETS.map((o) => (
                        <option key={o.id} value={o.id}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                    {row.pharmaceuticalFormKey === PRESCRIPTION_CUSTOM_KEY ? (
                      <input
                        value={row.pharmaceuticalForm}
                        onChange={(e) => {
                          const v = e.target.value;
                          setRows((prev) =>
                            prev.map((x, i) =>
                              i === idx
                                ? { ...x, pharmaceuticalForm: v }
                                : x,
                            ),
                          );
                        }}
                        placeholder="Ex.: comprimido revestido"
                        className="rounded-lg border px-2 py-2"
                      />
                    ) : null}
                  </label>
                  <label className="flex flex-col gap-1 text-sm">
                    <span className="text-slate-600">Quantidade</span>
                    <input
                      value={row.quantity}
                      onChange={(e) => {
                        const v = e.target.value;
                        setRows((prev) =>
                          prev.map((x, i) =>
                            i === idx ? { ...x, quantity: v } : x,
                          ),
                        );
                      }}
                      className="rounded-lg border px-2 py-2"
                    />
                  </label>
                  <label className="flex flex-col gap-1 text-sm sm:col-span-2">
                    <span className="text-slate-600">Posologia</span>
                    <textarea
                      value={row.posology}
                      onChange={(e) => {
                        const v = e.target.value;
                        setRows((prev) =>
                          prev.map((x, i) =>
                            i === idx ? { ...x, posology: v } : x,
                          ),
                        );
                      }}
                      rows={2}
                      className="rounded-lg border px-2 py-2"
                    />
                  </label>
                  {rows.length > 1 ? (
                    <button
                      type="button"
                      className="text-xs text-red-700 underline sm:col-span-2"
                      onClick={() =>
                        setRows((prev) => prev.filter((_, i) => i !== idx))
                      }
                    >
                      Remover linha
                    </button>
                  ) : null}
                </div>
              ))}
            </div>

            <label className="mt-4 flex flex-col gap-1 text-sm">
              <span className="text-slate-600">Observações</span>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={3}
                className="rounded-lg border px-2 py-2"
              />
            </label>

            <div className="mt-6 flex flex-wrap gap-2">
              <button
                type="submit"
                className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-700"
              >
                Emitir
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowForm(false);
                  resetFormFromDoctor();
                }}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm"
              >
                Cancelar
              </button>
            </div>
            </form>
          </div>
        ) : selected ? (
          <>
            <div className="prescriptions-no-print space-y-3">
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => window.print()}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                >
                  Imprimir / PDF
                </button>
                {selected.archivedAt ? (
                  <span className="rounded-lg bg-slate-200 px-3 py-2 text-sm text-slate-700">
                    Arquivada em {formatDt(selected.archivedAt)}
                  </span>
                ) : (
                  <button
                    type="button"
                    onClick={() => {
                      setArchiveReason('');
                      setArchiveOpen(true);
                    }}
                    className="rounded-lg border border-amber-600 px-3 py-2 text-sm text-amber-900"
                  >
                    Arquivar
                  </button>
                )}
              </div>
              {selected.archivedReason ? (
                <p className="rounded-lg bg-slate-100 p-3 text-xs text-slate-700">
                  <strong>Motivo do arquivamento:</strong>{' '}
                  {selected.archivedReason} (por {selected.archivedBy ?? '—'})
                </p>
              ) : null}
            </div>
            <RceViewer
              rx={selected}
              patientDisplayName={patient.name}
            />
          </>
        ) : (
          <p className="prescriptions-no-print rounded-xl border border-dashed border-slate-300 bg-slate-50 p-6 text-sm text-slate-600">
            Selecione uma prescrição na lista ou crie uma nova.
          </p>
        )}
      </div>

      {archiveOpen && selected ? (
        <div className="prescriptions-no-print fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
          <div className="w-full max-w-lg rounded-xl border bg-white p-6 shadow-xl">
            <h4 className="font-semibold text-slate-900">
              Arquivar prescrição
            </h4>
            <p className="mt-2 text-sm text-slate-600">
              Informe o motivo (obrigatório para auditoria). Esta ação não apaga
              o registro.
            </p>
            <textarea
              value={archiveReason}
              onChange={(e) => setArchiveReason(e.target.value)}
              rows={4}
              className="mt-3 w-full rounded-lg border px-3 py-2 text-sm"
              placeholder="Mínimo 5 caracteres"
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setArchiveOpen(false)}
                className="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100"
              >
                Cancelar
              </button>
              <button
                type="button"
                disabled={archiveBusy || archiveReason.trim().length < 5}
                onClick={() => void confirmArchive()}
                className="rounded-lg bg-amber-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              >
                Confirmar arquivamento
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
