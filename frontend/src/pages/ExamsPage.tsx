import { useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Upload, Download, Trash2 } from 'lucide-react';
import {
  addAlertMock,
  patchPatientMock,
} from '@/api/clinicalApi';
import { createExamHttp, uploadExamFileHttp } from '@/api/clinicalApi.exams.http';
import { useAppSession } from '@/context/AppSessionContext';
import { useToast } from '@/context/ToastContext';
import { usePatientDetail } from '@/hooks/usePatientDetail';
import type { Exam } from '@/types/domain';

type ExamFilter = 'all' | 'pending' | 'completed' | 'critical';

export function ExamsPage() {
  const navigate = useNavigate();
  const { showToast } = useToast();
  const { activePatientId, refreshAlertBadge } = useAppSession();
  const { patient, refetch } = usePatientDetail(activePatientId);
  const [filter, setFilter] = useState<ExamFilter>('all');
  const [selected, setSelected] = useState<Exam | null>(null);
  const [modalExam, setModalExam] = useState<Exam | null>(null);
  const [resultValue, setResultValue] = useState('');
  const [resultUnit, setResultUnit] = useState('mg/dL');
  const [criticalFlag, setCriticalFlag] = useState(false);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [newExamName, setNewExamName] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    if (!patient) {
      return [];
    }
    const list = patient.exams;
    if (filter === 'pending') {
      return list.filter((e) => e.status === 'pending');
    }
    if (filter === 'completed') {
      return list.filter((e) => e.status === 'completed');
    }
    if (filter === 'critical') {
      return list.filter((e) => e.status === 'critical');
    }
    return list;
  }, [patient, filter]);

  if (!activePatientId || !patient) {
    return (
      <p className="text-slate-600">Selecione um paciente para ver exames.</p>
    );
  }

  function openSimulate(ex: Exam) {
    setModalExam(ex);
    setResultValue('');
    setCriticalFlag(false);
    setResultUnit(
      ex.name.toLowerCase().includes('lactato') ? 'mmol/L' : 'mg/dL',
    );
  }

  async function confirmResult() {
    if (!patient || !modalExam) {
      return;
    }
    const status = criticalFlag ? 'critical' : 'completed';
    const resultStr = `${resultValue} ${resultUnit}`.trim();
    const interpretation =
      status === 'critical'
        ? `Valor crítico registrado (${resultStr}). Avaliação urgente recomendada (mock).`
        : `Resultado ${resultStr} dentro do fluxo de demonstração.`;

    await patchPatientMock(patient.id, {
      exams: [
        {
          id: modalExam.id,
          status,
          result: resultStr,
          interpretation,
        },
      ],
    });
    await refetch();
    await refreshAlertBadge();
    showToast(
      criticalFlag
        ? 'Resultado registrado. Alerta crítico emitido para equipe médica.'
        : 'Resultado registrado.',
    );
    if (criticalFlag) {
      navigate('/alerts');
    }
    setModalExam(null);
  }

  async function notifyResponsible() {
    if (!patient || !selected) {
      return;
    }
    await addAlertMock({
      patientId: patient.id,
      severity: 'moderate',
      category: 'exam',
      message: `Notificação: revisar ${selected.name} — ${selected.result ?? 'resultado disponível'}.`,
      team: 'doctors',
      resolved: false,
    });
    await refreshAlertBadge();
    showToast('Notificação registrada.');
  }

  async function createExam() {
    if (!patient || !newExamName.trim()) {
      showToast('Por favor, insira o nome do exame.');
      return;
    }
    
    try {
      setIsCreating(true);
      await createExamHttp(patient.id, newExamName.trim());
      await refetch();
      setCreateModalOpen(false);
      setNewExamName('');
      showToast('Exame criado com sucesso.');
    } catch (error) {
      console.error('Erro ao criar exame:', error);
      showToast('Erro ao criar exame.');
    } finally {
      setIsCreating(false);
    }
  }

  async function handleFileUpload(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file || !patient || !selected) {
      return;
    }

    try {
      setIsUploading(true);
      const updatedExam = await uploadExamFileHttp(patient.id, selected.id, file);
      setSelected(updatedExam);
      await refetch();
      showToast('Arquivo enviado com sucesso.');
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    } catch (error) {
      console.error('Erro ao fazer upload:', error);
      showToast('Erro ao enviar arquivo.');
    } finally {
      setIsUploading(false);
    }
  }

  function formatFileSize(bytes?: number): string {
    if (!bytes) return 'Tamanho desconhecido';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(2)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  }

  function getFileIcon(mime?: string): string {
    if (!mime) return '📄';
    if (mime.includes('pdf')) return '📕';
    if (mime.includes('image')) return '🖼️';
    if (mime.includes('word')) return '📘';
    if (mime.includes('sheet')) return '📗';
    return '📄';
  }

  async function downloadFile(attachmentPath: string, fileName: string) {
    if (!attachmentPath || !fileName) {
      showToast('Arquivo não disponível para download.');
      return;
    }

    try {
      const response = await fetch(attachmentPath);
      if (!response.ok) {
        throw new Error('Falha ao fazer download');
      }
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = fileName;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (error) {
      console.error('Erro ao fazer download:', error);
      showToast('Erro ao fazer download do arquivo.');
    }
  }

  async function deleteAttachment(index: number) {
    if (!selected || !selected.attachments) {
      return;
    }

    try {
      const updatedAttachments = selected.attachments.filter((_, i) => i !== index);
      const updatedExam = { ...selected, attachments: updatedAttachments };
      setSelected(updatedExam);
      
      // Aqui você poderia fazer uma chamada de API para deletar o arquivo no backend
      // Por enquanto, apenas atualizamos o estado local
      showToast('Arquivo removido.');
    } catch (error) {
      console.error('Erro ao remover arquivo:', error);
      showToast('Erro ao remover arquivo.');
    }
  }

  return (
    <div className="flex flex-col gap-4 lg:flex-row">
      <div className="min-w-0 flex-1 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold text-slate-900">
            Exames e pendências
          </h2>
          <button
            type="button"
            onClick={() => setCreateModalOpen(true)}
            className="flex items-center gap-2 rounded-lg bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-700"
          >
            <Plus className="h-4 w-4" />
            Novo Exame
          </button>
        </div>
        <div className="flex flex-wrap gap-2">
          {(
            [
              ['all', 'Todos'],
              ['pending', 'Pendentes'],
              ['completed', 'Concluídos'],
              ['critical', 'Críticos'],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setFilter(key)}
              className={`rounded-full px-3 py-1 text-sm font-medium ${
                filter === key
                  ? 'bg-teal-600 text-white'
                  : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="overflow-x-auto rounded-xl border border-[var(--color-border-subtle)] bg-white">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="border-b bg-slate-50 text-xs font-semibold uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">Exame</th>
                <th className="px-3 py-2">Solicitado em</th>
                <th className="px-3 py-2">Origem</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Ação</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((ex) => (
                <tr
                  key={ex.id}
                  className={`cursor-pointer border-b hover:bg-teal-50/50 ${
                    selected?.id === ex.id ? 'bg-teal-50' : ''
                  }`}
                  onClick={() => setSelected(ex)}
                >
                  <td className="px-3 py-2 font-medium">{ex.name}</td>
                  <td className="px-3 py-2 text-slate-600">
                    {new Date(ex.requestedAt).toLocaleString('pt-BR', {
                      day: '2-digit',
                      month: '2-digit',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${
                        ex.source === 'protocol'
                          ? 'bg-sky-100 text-sky-900'
                          : 'bg-slate-100 text-slate-700'
                      }`}
                    >
                      {ex.source === 'protocol' ? 'Protocolo' : 'Manual'}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    {ex.status === 'pending'
                      ? '🟡 Pendente'
                      : ex.status === 'completed'
                        ? '✅ Concluído'
                        : '🔴 Crítico'}
                  </td>
                  <td className="px-3 py-2">
                    {ex.status === 'pending' ? (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          openSimulate(ex);
                        }}
                        className="text-teal-700 underline"
                      >
                        Simular resultado
                      </button>
                    ) : (
                      '—'
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <aside className="w-full shrink-0 rounded-xl border border-[var(--color-border-subtle)] bg-white p-4 lg:w-80">
        {!selected ? (
          <p className="text-sm text-slate-500">
            Clique em um exame para ver detalhes.
          </p>
        ) : (
          <div className="space-y-3 text-sm">
            <h3 className="font-semibold text-slate-900">{selected.name}</h3>
            <p className="text-slate-600">
              <span className="font-medium">Método:</span> análise automatizada
              (mock)
            </p>
            <p className="text-slate-600">
              <span className="font-medium">Referência:</span> valores usuais
              laboratoriais institucionais (mock)
            </p>
            {selected.result ? (
              <p>
                <span className="font-medium">Resultado:</span> {selected.result}
              </p>
            ) : null}
            {selected.interpretation ? (
              <p className="text-slate-700">
                <span className="font-medium">Interpretação do assistente:</span>{' '}
                {selected.interpretation}
              </p>
            ) : null}
            {selected.attachments && selected.attachments.length > 0 ? (
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                <p className="text-xs font-medium text-slate-600 uppercase mb-2">
                  Arquivos ({selected.attachments.length})
                </p>
                <div className="space-y-2">
                  {selected.attachments.map((attachment, index) => (
                    <div
                      key={`${attachment.name}-${index}`}
                      className="flex items-start gap-3 rounded bg-white p-2"
                    >
                      <span className="text-xl">{getFileIcon(attachment.mime)}</span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-medium text-slate-900">
                          {attachment.name}
                        </p>
                        <p className="text-xs text-slate-500">
                          {formatFileSize(attachment.size)}
                        </p>
                      </div>
                      <div className="flex flex-shrink-0 gap-1">
                        <button
                          type="button"
                          onClick={() =>
                            void downloadFile(attachment.path, attachment.name)
                          }
                          className="rounded p-1 text-teal-600 hover:bg-teal-50"
                          title="Fazer download"
                        >
                          <Download className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          onClick={() => void deleteAttachment(index)}
                          className="rounded p-1 text-red-600 hover:bg-red-50"
                          title="Remover arquivo"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
            <div className="space-y-2 pt-2">
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={isUploading}
                className="flex w-full items-center justify-center gap-2 rounded-lg border border-teal-600 py-2 text-sm font-medium text-teal-800 hover:bg-teal-50 disabled:bg-teal-50 disabled:opacity-50"
              >
                <Upload className="h-4 w-4" />
                {isUploading ? 'Enviando...' : 'Fazer upload'}
              </button>
              <input
                type="file"
                ref={fileInputRef}
                onChange={(e) => void handleFileUpload(e)}
                className="hidden"
                accept="*/*"
              />
              <button
                type="button"
                onClick={() => void notifyResponsible()}
                className="w-full rounded-lg border border-teal-600 py-2 text-sm font-medium text-teal-800 hover:bg-teal-50"
              >
                Notificar responsável
              </button>
            </div>
          </div>
        )}
      </aside>

      {modalExam ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
          <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
            <h3 className="font-semibold text-slate-900">
              Simular resultado — {modalExam.name}
            </h3>
            <div className="mt-4 flex gap-2">
              <input
                type="text"
                value={resultValue}
                onChange={(e) => setResultValue(e.target.value)}
                placeholder="Valor"
                className="flex-1 rounded border px-3 py-2 text-sm"
              />
              <input
                value={resultUnit}
                onChange={(e) => setResultUnit(e.target.value)}
                className="w-24 rounded border px-2 py-2 text-sm"
              />
            </div>
            <label className="mt-3 flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={criticalFlag}
                onChange={(e) => setCriticalFlag(e.target.checked)}
              />
              Marcar como crítico
            </label>
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setModalExam(null)}
                className="rounded px-4 py-2 text-sm text-slate-600"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={() => void confirmResult()}
                className="rounded bg-teal-600 px-4 py-2 text-sm text-white"
              >
                Confirmar
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {createModalOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
          <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
            <h3 className="font-semibold text-slate-900">
              Criar novo exame
            </h3>
            <input
              type="text"
              value={newExamName}
              onChange={(e) => setNewExamName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  void createExam();
                }
              }}
              placeholder="Nome do exame"
              className="mt-4 w-full rounded border px-3 py-2 text-sm"
              autoFocus
            />
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setCreateModalOpen(false);
                  setNewExamName('');
                }}
                className="rounded px-4 py-2 text-sm text-slate-600"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={() => void createExam()}
                disabled={isCreating}
                className="rounded bg-teal-600 px-4 py-2 text-sm text-white disabled:bg-teal-400"
              >
                {isCreating ? 'Criando...' : 'Criar'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
