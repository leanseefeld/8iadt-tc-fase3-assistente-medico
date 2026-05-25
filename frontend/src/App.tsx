import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AppSessionProvider } from '@/context/AppSessionContext';
import { ToastProvider } from '@/context/ToastContext';
import { ProtectedLayout } from '@/layouts/ProtectedLayout';
import { AlertsPage } from '@/pages/AlertsPage';
import { ChatPage } from '@/pages/ChatPage';
import { CheckInPage } from '@/pages/CheckInPage';
import { DashboardPage } from '@/pages/DashboardPage';
import { ExamsPage } from '@/pages/ExamsPage';
import { LoginPage } from '@/pages/LoginPage';
import { PrescriptionsPage } from '@/pages/PrescriptionsPage';

export function App() {
  return (
    <ToastProvider>
      <AppSessionProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<ProtectedLayout />}>
              <Route
                path="/"
                element={<Navigate to="/dashboard" replace />}
              />
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/checkin" element={<CheckInPage />} />
              <Route path="/chat" element={<ChatPage />} />
              <Route path="/exams" element={<ExamsPage />} />
              <Route
                path="/prescriptions"
                element={<PrescriptionsPage />}
              />
              <Route path="/alerts" element={<AlertsPage />} />
              <Route
                path="/exams-pendencies"
                element={<Navigate to="/exams" replace />}
              />
              <Route
                path="*"
                element={<Navigate to="/dashboard" replace />}
              />
            </Route>
          </Routes>
        </BrowserRouter>
      </AppSessionProvider>
    </ToastProvider>
  );
}
