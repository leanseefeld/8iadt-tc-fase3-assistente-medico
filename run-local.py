#!/usr/bin/env python3
"""Orquestrador local cross-platform para backend + frontend."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import http.client
from pathlib import Path


def command_exists(command_name: str) -> bool:
    return shutil.which(command_name) is not None


def is_ollama_running() -> bool:
    """Verifica se o serviço do Ollama está acessível na porta padrão."""
    try:
        conn = http.client.HTTPConnection("localhost", 11434, timeout=2)
        conn.request("GET", "/")
        response = conn.getresponse()
        return response.status == 200
    except Exception:
        return False


def resolve_repo_root() -> Path:
    return Path(__file__).resolve().parent


def resolve_venv_python(repo_root: Path) -> Path:
    candidates = [repo_root / ".venv", repo_root / "ambiente_virtual"]
    for base in candidates:
        windows_python = base / "Scripts" / "python.exe"
        unix_python = base / "bin" / "python"
        if windows_python.exists():
            return windows_python
        if unix_python.exists():
            return unix_python

    default_venv = repo_root / ".venv"
    print("Nenhum venv encontrado. Criando ambiente virtual em '.venv'...")
    subprocess.run([sys.executable, "-m", "venv", str(default_venv)], cwd=str(repo_root), check=True)

    windows_python = default_venv / "Scripts" / "python.exe"
    unix_python = default_venv / "bin" / "python"
    if windows_python.exists():
        return windows_python
    if unix_python.exists():
        return unix_python
    raise RuntimeError("Falha ao criar o venv em '.venv'. Verifique sua instalação do Python.")


def ensure_backend_env_file(repo_root: Path) -> None:
    backend_env = repo_root / "backend" / ".env"
    backend_env_example = repo_root / "backend" / ".env.example"
    if not backend_env.exists() and backend_env_example.exists():
        backend_env.write_text(backend_env_example.read_text(encoding="utf-8"), encoding="utf-8")
        print("Arquivo backend/.env criado a partir de .env.example")


def run_checked(command: list[str], cwd: Path, env: dict | None = None) -> None:
    print(f"> {' '.join(command)}")
    use_shell = os.name == 'nt'
    current_env = env if env is not None else os.environ.copy()
    subprocess.run(command, cwd=str(cwd), check=True, shell=use_shell, env=current_env)


def start_service(command: list[str], cwd: Path, env: dict | None = None) -> int:
    """Inicia um serviço mantendo stdout/stderr no console (sem logs em arquivo)."""
    use_shell = os.name == 'nt'
    current_env = env if env is not None else os.environ.copy()

    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=current_env,
        shell=use_shell
    )
    return process.pid


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sobe backend + frontend localmente.")
    parser.add_argument("--setup", action="store_true", help="Instala dependências Python e Node.")
    parser.add_argument("--build-vectorstore", action="store_true", help="Executa a pipeline RAG completa.")
    parser.add_argument("--skip-migrations", action="store_true", help="Pula migrations e seed.")
    parser.add_argument("--backend-port", type=int, default=8000, help="Porta do backend FastAPI.")
    parser.add_argument("--frontend-port", type=int, default=5173, help="Porta do frontend Vite.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = resolve_repo_root()
    venv_python = resolve_venv_python(repo_root)

    if not command_exists("node"):
        raise RuntimeError("Node.js não encontrado no PATH.")
    if not command_exists("npm"):
        raise RuntimeError("npm não encontrado no PATH.")

    if args.setup:
        print("Instalando dependências Python...")
        run_checked([str(venv_python), "-m", "pip", "install", "-e", str(repo_root / "llm")], repo_root)
        run_checked([str(venv_python), "-m", "pip", "install", "-e", str(repo_root / "backend")], repo_root)

        print("Instalando dependências do frontend...")
        run_checked(["npm", "install"], repo_root / "frontend")

    ensure_backend_env_file(repo_root)

    if not args.skip_migrations:
        print("Aplicando migrations e seed no backend...")
        run_checked([str(venv_python), "-m", "alembic", "upgrade", "head"], repo_root / "backend")
        run_checked([str(venv_python), "scripts/seed_patients.py"], repo_root / "backend")

    # Variáveis de ambiente para os modelos
    medico_vars = {
        "MEDICO_OLLAMA_EMBED_MODEL": "nomic-embed-text",
        "MEDICO_OLLAMA_CHAT_MODEL": "gemma4:e4b-it-q4_K_M"
    }

    if args.build_vectorstore:
        print("\n--- Verificando status do Ollama ---")
        if not is_ollama_running():
            print("❌ Erro: O serviço Ollama não foi detectado!")
            print("Por favor, certifique-se de que o Ollama está instalado e aberto.")
            return 1

        # Garante que os modelos necessários estão baixados
        for model in medico_vars.values():
            print(f"✔ Garantindo modelo '{model}'...")
            run_checked(["ollama", "pull", model], repo_root)

        print("\nIniciando pipeline de ingestão de dados (RAG)...")

        llm_env = os.environ.copy()
        llm_env.update(medico_vars)
        llm_src = str(repo_root / "llm" / "src")
        llm_env["PYTHONPATH"] = f"{llm_src}{os.pathsep}{llm_env.get('PYTHONPATH', '')}"

        steps = [
            ("download-pcdt", ["pcdt_ingest.cli_pcdt", "--max-files", "20", "--force"]),
            ("extract-pcdt-markdown", ["pcdt_ingest.cli_extract", "--workers", "6", "--force"]),
            ("chunk-pcdt", ["pcdt_ingest.cli_chunk", "--workers", "6", "--force"]),
            ("build-vectorstore", ["pcdt_ingest.cli_embed", "--force"])
        ]

        for display_name, module_info in steps:
            print(f"\n--- Etapa: {display_name} ---")
            cmd = [str(venv_python), "-m"] + module_info
            run_checked(cmd, repo_root, env=llm_env)

    # Inicia backend
    print(f"\nIniciando backend na porta {args.backend_port}...")
    backend_env = os.environ.copy()
    backend_env.update(medico_vars)
    backend_pid = start_service(
        [str(venv_python), "-m", "uvicorn", "assistente_medico_api.main:app", "--reload", "--host", "0.0.0.0", "--port",
         str(args.backend_port)],
        repo_root / "backend",
        env=backend_env
    )

    # Inicia frontend
    print(f"Iniciando frontend na porta {args.frontend_port}...")
    frontend_env = os.environ.copy()
    frontend_env.update(medico_vars)
    frontend_env["VITE_API_BASE_URL"] = f"http://localhost:{args.backend_port}/api"

    frontend_pid = start_service(
        ["npm", "run", "dev"],
        repo_root / "frontend",
        env=frontend_env
    )

    print(f"\nAmbiente iniciado com sucesso!")
    print(f"- Backend:  http://localhost:{args.backend_port}/docs (PID: {backend_pid})")
    print(f"- Frontend: http://localhost:{args.frontend_port} (PID: {frontend_pid})")
    print("\nLogs sendo impressos diretamente no console acima.")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nEncerrando orquestrador...")
        sys.exit(0)