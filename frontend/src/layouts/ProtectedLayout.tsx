import { Navigate, useLocation } from 'react-router-dom';
import { useAppSession } from '@/context/AppSessionContext';
import { AppLayout } from '@/layouts/AppLayout';

/** Só renderiza o app principal após login fake; caso contrário redireciona para /login. */
export function ProtectedLayout() {
  const { activeDoctor } = useAppSession();
  const location = useLocation();

  if (!activeDoctor) {
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: location.pathname + location.search }}
      />
    );
  }

  return <AppLayout />;
}
