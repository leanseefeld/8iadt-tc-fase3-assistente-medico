import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

interface ConversationRefreshContextValue {
  refreshKey: number;
  refreshConversations: () => void;
}

const ConversationRefreshContext =
  createContext<ConversationRefreshContextValue | null>(null);

export function ConversationRefreshProvider({ children }: { children: ReactNode }) {
  const [refreshKey, setRefreshKey] = useState(0);
  const refreshConversations = useCallback(() => {
    setRefreshKey((k) => k + 1);
  }, []);

  const value = useMemo(
    () => ({ refreshKey, refreshConversations }),
    [refreshKey, refreshConversations],
  );

  return (
    <ConversationRefreshContext.Provider value={value}>
      {children}
    </ConversationRefreshContext.Provider>
  );
}

export function useConversationRefresh(): ConversationRefreshContextValue {
  const ctx = useContext(ConversationRefreshContext);
  if (!ctx) {
    throw new Error(
      'useConversationRefresh deve ser usado dentro de ConversationRefreshProvider',
    );
  }
  return ctx;
}
