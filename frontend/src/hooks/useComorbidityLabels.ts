import { useEffect, useMemo, useState } from 'react';

import { getComorbidities } from '@/api/clinicalApi.comorbidities';

type CodeToLabelFn = (code: string) => string;

export function useComorbidityLabels(): {
  codeToLabel: CodeToLabelFn;
  loading: boolean;
} {
  const [loading, setLoading] = useState(true);
  const [options, setOptions] = useState<Array<{ code: string; label: string }>>([]);

  useEffect(() => {
    let active = true;

    async function load() {
      setLoading(true);
      try {
        const response = await getComorbidities();
        if (!active) return;
        setOptions(
          (response.comorbidities || []).map((o) => ({ code: o.code, label: o.label })),
        );
      } catch {
        // Falha aqui não deve quebrar a UI; fallback é retornar o próprio código.
        if (!active) return;
        setOptions([]);
      } finally {
        if (!active) return;
        setLoading(false);
      }
    }

    void load();
    return () => {
      active = false;
    };
  }, []);

  const codeToLabel = useMemo<CodeToLabelFn>(() => {
    const map = new Map<string, string>();
    options.forEach((o) => map.set(o.code, o.label));
    return (code: string) => map.get(code) || code;
  }, [options]);

  return { codeToLabel, loading };
}

