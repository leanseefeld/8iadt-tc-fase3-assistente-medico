import { Search, X } from 'lucide-react';
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from 'react';
import type { Patient } from '@/types/patient';
import { searchPatientsMock } from '@/api/mockApi';
import { usePatientContext } from '@/context/PatientContext';

const DEBOUNCE_MS = 280;

export function PatientLookup() {
  const { setSelectedPatient } = usePatientContext();
  const [expanded, setExpanded] = useState(false);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Patient[]>([]);
  const [loading, setLoading] = useState(false);
  const listId = useId();
  const wrapRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!expanded) {
      return;
    }
    const t = window.setTimeout(() => {
      inputRef.current?.focus();
    }, 0);
    return () => window.clearTimeout(t);
  }, [expanded]);

  useEffect(() => {
    if (!expanded) {
      return;
    }
    let cancelled = false;
    setLoading(true);
    const t = window.setTimeout(() => {
      void searchPatientsMock(query).then((list) => {
        if (!cancelled) {
          setResults(list);
          setLoading(false);
        }
      });
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [query, expanded]);

  const collapse = useCallback(() => {
    setExpanded(false);
    setQuery('');
    setResults([]);
  }, []);

  useEffect(() => {
    if (!expanded) {
      return;
    }
    function onDocMouseDown(e: MouseEvent) {
      if (
        wrapRef.current &&
        !wrapRef.current.contains(e.target as Node)
      ) {
        collapse();
      }
    }
    document.addEventListener('mousedown', onDocMouseDown);
    return () => document.removeEventListener('mousedown', onDocMouseDown);
  }, [expanded, collapse]);

  function pick(patient: Patient) {
    setSelectedPatient(patient);
    collapse();
  }

  if (!expanded) {
    return (
      <button
        type="button"
        onClick={() => setExpanded(true)}
        className="flex h-10 w-10 items-center justify-center rounded-lg border border-[var(--color-border-subtle)] bg-white text-slate-600 shadow-sm transition-colors hover:border-teal-300 hover:text-teal-700"
        aria-label="Buscar paciente por ID ou nome"
      >
        <Search className="h-5 w-5" aria-hidden />
      </button>
    );
  }

  return (
    <div ref={wrapRef} className="relative w-72 max-w-[85vw]">
      <div className="flex items-center gap-1 rounded-lg border border-[var(--color-border-subtle)] bg-white shadow-sm">
        <Search className="ml-2 h-4 w-4 shrink-0 text-slate-400" aria-hidden />
        <input
          ref={inputRef}
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="ID ou nome do paciente…"
          className="min-w-0 flex-1 border-0 bg-transparent py-2 pr-2 text-sm outline-none focus:ring-0"
          aria-autocomplete="list"
          aria-controls={listId}
          aria-expanded={results.length > 0}
        />
        <button
          type="button"
          onClick={collapse}
          className="mr-1 flex h-8 w-8 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100"
          aria-label="Fechar busca"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <ul
        id={listId}
        role="listbox"
        className="absolute left-0 right-0 top-full z-30 mt-1 max-h-56 overflow-auto rounded-lg border border-[var(--color-border-subtle)] bg-white py-1 shadow-lg"
      >
        {loading ? (
          <li className="px-3 py-2 text-sm text-slate-500">Buscando…</li>
        ) : results.length === 0 ? (
          <li className="px-3 py-2 text-sm text-slate-500">
            Nenhum paciente encontrado.
          </li>
        ) : (
          results.map((p) => (
            <li key={p.id} role="presentation">
              <button
                type="button"
                role="option"
                className="flex w-full flex-col items-start gap-0.5 px-3 py-2 text-left text-sm hover:bg-teal-50"
                onClick={() => pick(p)}
              >
                <span className="font-medium text-slate-800">{p.name}</span>
                <span className="text-xs text-slate-500">{p.id}</span>
              </button>
            </li>
          ))
        )}
      </ul>
    </div>
  );
}
