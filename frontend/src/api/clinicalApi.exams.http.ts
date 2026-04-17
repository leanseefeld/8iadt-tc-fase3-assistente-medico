import { API_BASE_URL } from '@/api/client';
import type { Exam } from '@/types/domain';

export async function createExamHttp(patientId: string, name: string): Promise<Exam> {
  const res = await fetch(`${API_BASE_URL}/patients/${patientId}/exams`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) {
    throw new Error(`Falha ao criar exame: HTTP ${res.status}`);
  }
  return ((await res.json()) as { exam: Exam }).exam;
}

export async function patchExamHttp(
  patientId: string,
  examId: string,
  patch: Partial<Pick<Exam, 'status' | 'result' | 'interpretation'>>,
): Promise<Exam> {
  const res = await fetch(`${API_BASE_URL}/patients/${patientId}/exams/${examId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(patch),
  });
  if (!res.ok) {
    throw new Error(`Falha ao atualizar exame: HTTP ${res.status}`);
  }
  return ((await res.json()) as { exam: Exam }).exam;
}

export async function uploadExamFileHttp(
  patientId: string,
  examId: string,
  file: File,
): Promise<Exam> {
  const form = new FormData();
  form.append('file', file);

  const res = await fetch(`${API_BASE_URL}/patients/${patientId}/exams/${examId}/upload`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) {
    throw new Error(`Falha no upload de exame: HTTP ${res.status}`);
  }
  return ((await res.json()) as { exam: Exam }).exam;
}
