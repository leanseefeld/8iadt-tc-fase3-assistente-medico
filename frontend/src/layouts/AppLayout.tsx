import { Outlet } from 'react-router-dom';
import { Sidebar } from '@/components/Sidebar';
import { TopBar } from '@/components/TopBar';
import { ChatSessionProvider } from '@/context/ChatSessionContext';
import { ConversationRefreshProvider } from '@/context/ConversationRefreshContext';

export function AppLayout() {
  return (
    <ConversationRefreshProvider>
      <ChatSessionProvider>
        <div className="flex min-h-screen">
          <Sidebar />
          <div className="flex min-w-0 flex-1 flex-col">
            <TopBar />
            <main className="flex-1 overflow-auto p-6">
              <Outlet />
            </main>
          </div>
        </div>
      </ChatSessionProvider>
    </ConversationRefreshProvider>
  );
}
