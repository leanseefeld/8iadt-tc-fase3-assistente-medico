import { useState } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useAppSession } from '@/context/AppSessionContext';
import { useToast } from '@/context/ToastContext';
import { MOCK_DOCTORS } from '@/mocks/internal/doctors';

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { showToast } = useToast();
  const { activeDoctor, login } = useAppSession();
  const from =
    (location.state as { from?: string } | null)?.from ?? '/dashboard';

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);

  if (activeDoctor) {
    return <Navigate to={from === '/login' ? '/dashboard' : from} replace />;
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const doc = login(username.trim(), password);
    setBusy(false);
    if (doc == null) {
      showToast('Usuário ou senha inválidos.');
      return;
    }
    showToast(`Olá, ${doc.name}.`);
    navigate(from, { replace: true });
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-slate-100 px-4 py-10">
      <div className="w-full max-w-md rounded-2xl border border-[var(--color-border-subtle)] bg-white p-8 shadow-lg">
        <h1 className="text-center text-xl font-bold text-teal-900">
          Assistente Médico
        </h1>
        <p className="mt-1 text-center text-sm text-slate-600">
          Login de demonstração (sem servidor de autenticação)
        </p>

        <form onSubmit={handleSubmit} className="mt-8 space-y-4">
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">Usuário</span>
            <input
              type="text"
              name="username"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="rounded-lg border border-slate-300 px-3 py-2"
              placeholder="ex.: ana.souza"
              required
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">Senha</span>
            <input
              type="password"
              name="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="rounded-lg border border-slate-300 px-3 py-2"
              placeholder="•••••••"
              required
            />
          </label>
          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-xl bg-teal-600 py-3 text-sm font-semibold text-white hover:bg-teal-700 disabled:opacity-50"
          >
            Entrar
          </button>
        </form>

        <div className="mt-8 rounded-lg bg-slate-50 p-4 text-xs text-slate-600">
          <p className="font-semibold text-slate-800">Contas de demonstração</p>
          <ul className="mt-2 space-y-1.5">
            {MOCK_DOCTORS.map((d) => (
              <li key={d.id}>
                <span className="font-mono text-slate-800">{d.username}</span>
                {' / '}
                <span className="font-mono">{d.password}</span>
                <span className="text-slate-500"> — {d.name}</span>
              </li>
            ))}
          </ul>
        </div>

        <p className="mt-6 text-center text-xs text-slate-500">
          Protótipo local — não use dados reais de pacientes em produção.
        </p>
      </div>
      <p className="mt-6 max-w-md text-center text-sm text-slate-600">
        Após entrar, use <strong>Nova Admissão</strong> no menu lateral para o
        check-in.
      </p>
    </div>
  );
}
