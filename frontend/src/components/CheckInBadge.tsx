import { getCheckInStatus } from '@/lib/checkInStatus';
import type { Patient } from '@/types/patient';

const LABELS: Record<
  ReturnType<typeof getCheckInStatus>,
  { title: string; className: string }
> = {
  ok: {
    title: 'Check-in recente (até 12 horas)',
    className: 'bg-emerald-500',
  },
  stale: {
    title: 'Check-in há mais de 12 horas',
    className: 'bg-amber-400',
  },
  none: {
    title: 'Sem check-in / não internado',
    className: 'bg-slate-300',
  },
};

interface CheckInBadgeProps {
  patient: Patient;
}

export function CheckInBadge({ patient }: CheckInBadgeProps) {
  const status = getCheckInStatus(patient.checkedInAt);
  const cfg = LABELS[status];

  return (
    <span
      className="inline-flex items-center gap-2"
      title={cfg.title}
    >
      <span
        className={`h-2.5 w-2.5 shrink-0 rounded-full ${cfg.className}`}
        aria-hidden
      />
      <span className="text-xs font-medium text-slate-600">Internação</span>
    </span>
  );
}
