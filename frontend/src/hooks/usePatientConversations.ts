import { useEffect, useState } from 'react';
import { listAssistantConversations } from '@/api/clinicalApi';
import { useConversationRefresh } from '@/context/ConversationRefreshContext';
import type { ConversationSummary } from '@/types/domain';

export function usePatientConversations(patientId: string | null) {
  const { refreshKey } = useConversationRefresh();
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!patientId) {
      setConversations([]);
      setError(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    void listAssistantConversations(patientId)
      .then((res) => {
        if (!cancelled) {
          setConversations(res.conversations);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError('Não foi possível carregar as conversas.');
          setConversations([]);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [patientId, refreshKey]);

  return { conversations, loading, error };
}
