import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { PatientProvider } from '@/context/PatientContext';
import { AppLayout } from '@/layouts/AppLayout';
import { ChatPage } from '@/pages/ChatPage';
import { DashboardPage } from '@/pages/DashboardPage';
import { DecisionFlowPage } from '@/pages/DecisionFlowPage';
import { ExamsPendenciesPage } from '@/pages/ExamsPendenciesPage';
import { SuggestedActionsPage } from '@/pages/SuggestedActionsPage';

export function App() {
  return (
    <BrowserRouter>
      <PatientProvider>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/decision-flow" element={<DecisionFlowPage />} />
            <Route
              path="/exams-pendencies"
              element={<ExamsPendenciesPage />}
            />
            <Route
              path="/suggested-actions"
              element={<SuggestedActionsPage />}
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </PatientProvider>
    </BrowserRouter>
  );
}
