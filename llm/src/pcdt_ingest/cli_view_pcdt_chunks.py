"""CLI: serve a pasta ``llm/`` via HTTP para o visualizador de chunks PCDT no browser."""

from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
import sys

from pcdt_ingest.paths import data_root

# Caminho do ficheiro do visualizador relativamente à raiz ``llm/`` (fora de ``llm/data``, versionado no git).
_VIEWER_RELATIVE = "tools/pcdt-chunks-viewer/index.html"


def main(argv: list[str] | None = None) -> int:
    """Arranca um servidor HTTP estático sobre o diretório ``llm/`` e imprime o URL do visualizador."""
    parser = argparse.ArgumentParser(
        description=(
            "Serve a pasta llm/ por HTTP para abrir o visualizador de chunks PCDT no browser "
            "(dados em llm/data/)."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        metavar="N",
        help="Porta TCP.",
    )
    parser.add_argument(
        "--bind",
        default="127.0.0.1",
        metavar="ADDR",
        help="Endereço de escuta (ex.: 127.0.0.1 ou 0.0.0.0).",
    )
    args = parser.parse_args(argv)

    if args.port < 1 or args.port > 65535:
        print("Erro: --port deve estar entre 1 e 65535.", file=sys.stderr)
        return 2

    # Raiz estática = llm/ (inclui tools/ e expõe data/ para fetch no visualizador).
    llm_root = data_root().parent.resolve()
    handler_factory = functools.partial(
        http.server.SimpleHTTPRequestHandler,
        directory=str(llm_root),
    )

    socketserver.ThreadingTCPServer.allow_reuse_address = True
    try:
        with socketserver.ThreadingTCPServer((args.bind, args.port), handler_factory) as httpd:
            # URL amigável no browser quando bind é 0.0.0.0 ou ::.
            display_host = args.bind
            if display_host in ("0.0.0.0", "::"):
                display_host = "127.0.0.1"
            base = f"http://{display_host}:{args.port}"
            viewer_url = f"{base}/{_VIEWER_RELATIVE}"
            print(viewer_url)
            print("Abra o URL acima no browser para o visualizador de chunks PCDT.")
            print("Ctrl+C para encerrar o servidor.")
            httpd.serve_forever()
    except OSError as e:
        print(f"Erro ao iniciar o servidor: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nServidor encerrado.", file=sys.stderr)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
