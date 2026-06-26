"""CLI: avaliação comparativa de retrieval RAG (1q / Nq / RRF / 1q+Nq).

Wrapper que delega para ``llm/scripts/rag_eval_multiquery.py``, o qual
resolve o sys.path do backend e as dependências de avaliação de forma
auto-contida.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

# scripts/rag_eval_multiquery.py está dois níveis acima do pacote (llm/scripts/).
_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "rag_eval_multiquery.py"


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada do comando ``eval-rag``."""
    if not _SCRIPT.exists():
        print(f"Erro: script não encontrado em {_SCRIPT}", file=sys.stderr)
        return 2

    spec = importlib.util.spec_from_file_location("rag_eval_multiquery", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    args = mod.parse_args(argv)
    return asyncio.run(mod.run(args))


if __name__ == "__main__":
    raise SystemExit(main())
