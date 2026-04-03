import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AppSessionProvider } from '@/context/AppSessionContext';
import { ToastProvider } from '@/context/ToastContext';
import { AppLayout } from '@/layouts/AppLayout';
import { AlertsPage } from '@/pages/AlertsPage';
import { ChatPage } from '@/pages/ChatPage';
import { CheckInPage } from '@/pages/CheckInPage';
import { DashboardPage } from '@/pages/DashboardPage';
import { DecisionFlowPage } from '@/pages/DecisionFlowPage';
import { ExamsPage } from '@/pages/ExamsPage';
import { SuggestedActionsPage } from '@/pages/SuggestedActionsPage';

export function App() {
  return (
    <ToastProvider>
      <AppSessionProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<AppLayout />}>
              <Route
                path="/"
                element={<Navigate to="/dashboard" replace />}
              />
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/checkin" element={<CheckInPage />} />
              <Route path="/chat" element={<ChatPage />} />
              <Route path="/flow" element={<DecisionFlowPage />} />
              <Route path="/exams" element={<ExamsPage />} />
              <Route
                path="/suggested-actions"
                element={<SuggestedActionsPage />}
              />
              <Route path="/alerts" element={<AlertsPage />} />
              <Route
                path="/decision-flow"
                element={<Navigate to="/flow" replace />}
              />
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
