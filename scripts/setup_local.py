"""Create a disposable local environment, download embeddings, and index CSV data.

Run from a normal terminal with internet: python3 scripts/setup_local.py
No secrets are printed. No global Python packages or global model caches are used
unless the user has explicitly overridden the cache environment variables.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]


def enable_semantic(model):
    path = ROOT / ".env"
    text = path.read_text() if path.exists() else (ROOT / ".env.example").read_text()
    lines = text.splitlines()
    updated = False
    for i, line in enumerate(lines):
        if line.strip().startswith("SEMANTIC_MODEL="):
            lines[i] = "SEMANTIC_MODEL=" + model
            updated = True
            break
    if not updated:
        lines.append("SEMANTIC_MODEL=" + model)
    path.write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="Embedding model ID; defaults to .env or multilingual-e5-small")
    parser.add_argument("--browser", action="store_true", help="Also download Chromium for rendered collection")
    parser.add_argument("--no-model-download", action="store_true", help="Install dependencies but defer embedding download/indexing")
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        raise SystemExit("Python 3.10 or newer is required.")
    sys.path.insert(0, str(ROOT))
    from app.config import LOCAL_CACHE
    model = args.model or os.getenv("SEMANTIC_MODEL") or "intfloat/multilingual-e5-small"
    directory = ROOT / ".venv"
    python = directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        print("Creating project-local .venv…", flush=True)
        venv.EnvBuilder(with_pip=True).create(directory)
    if not LOCAL_CACHE.resolve().is_relative_to(directory.resolve()):
        raise SystemExit("Local setup requires ATLAS_CACHE_DIR to be inside .venv. Remove the external cache override before continuing.")
    pip_cache = LOCAL_CACHE / "pip"
    pip_cache.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    # Prevent shell/user pip configuration from redirecting installs to a global
    # prefix, --user directory or arbitrary target. Do not modify the user's shell.
    for key in list(env):
        if key.startswith("PIP_") or key in ("PYTHONPATH", "PYTHONHOME"):
            env.pop(key, None)
    env["PIP_CONFIG_FILE"] = os.devnull
    env["PIP_REQUIRE_VIRTUALENV"] = "true"
    env["PYTHONNOUSERSITE"] = "1"
    env["HF_HOME"] = str(LOCAL_CACHE / "huggingface")
    env["HF_HUB_CACHE"] = str(LOCAL_CACHE / "huggingface" / "hub")
    env["HF_XET_CACHE"] = str(LOCAL_CACHE / "huggingface" / "xet")
    env["SENTENCE_TRANSFORMERS_HOME"] = str(LOCAL_CACHE / "sentence-transformers")
    env["TORCH_HOME"] = str(LOCAL_CACHE / "torch")
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(LOCAL_CACHE / "ms-playwright")
    identity = subprocess.check_output([str(python), "-c", "import json,sys; print(json.dumps({'prefix':sys.prefix,'base':sys.base_prefix}))"], cwd=ROOT, env=env, text=True)
    import json
    identity = json.loads(identity)
    if identity["prefix"] == identity["base"] or Path(identity["prefix"]).resolve() != directory.resolve():
        raise SystemExit("Refusing installation: interpreter is not this project's .venv.")
    configuration = directory / "pyvenv.cfg"
    if configuration.exists() and "include-system-site-packages = true" in configuration.read_text().lower():
        raise SystemExit("Refusing installation: this .venv exposes global site-packages. Recreate it without --system-site-packages.")
    # app.config configured the local HF, Torch and Playwright cache paths before
    # any third-party library is imported in a child process.
    def run(arguments):
        subprocess.run([str(python), *arguments], cwd=ROOT, env=env, check=True)
    try:
        print("Installing local requirements into .venv…", flush=True)
        run(["-m", "pip", "install", "--require-virtualenv", "--disable-pip-version-check", "--cache-dir", str(pip_cache), "-r", "requirements.txt", "-r", "requirements-semantic.txt", "-r", "requirements-collector.txt"])
        run(["-m", "app", "ingest"])
        if not args.no_model_download:
            print(f"Downloading/caching {model} and building local embeddings…", flush=True)
            run(["-m", "app", "embed", "--model", model])
            # Enable only after the weights and derived embedding index exist.
            # Preserve all existing credentials and other settings in .env.
            enable_semantic(model)
        if args.browser:
            print("Downloading Chromium into the project-local browser cache…", flush=True)
            run(["-m", "playwright", "install", "chromium"])
        run(["-m", "unittest", "discover", "-s", "tests", "-v"])
    except subprocess.CalledProcessError:
        raise SystemExit("Setup did not finish. Resolve the reported installation/network issue and re-run the same command; the existing .venv/cache is reusable. No global packages were installed.") from None
    print("\nLocal setup complete. Start with:")
    print("  .venv/bin/python -m app serve" if os.name != "nt" else r"  .venv\Scripts\python -m app serve")
    if args.no_model_download:
        print("Semantic search is not enabled by this setup run; model download was explicitly deferred.")
    else:
        print("Semantic search is enabled in .env. Only the embedding weights run locally; chat generation still uses OpenRouter.")


if __name__ == "__main__":
    main()
