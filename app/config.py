"""Small dependency-free configuration loader. Secrets never leave the backend."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
DB = DATA / "search.db"


def load_env():
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_env()

# Lightweight Docker builds cannot load host-side embedding settings accidentally.
# Semantic builds contain their weights/index already and need no startup download.
if os.getenv("ATLAS_BUILD_SEMANTIC") == "0":
    os.environ["SEMANTIC_MODEL"] = ""
elif os.getenv("ATLAS_BUILD_SEMANTIC") == "1":
    os.environ["SEMANTIC_MODEL"] = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")

# Keep local test dependencies and downloaded weights disposable together.
# Explicit environment overrides support a mounted cache in a future container.
LOCAL_CACHE = Path(os.getenv("ATLAS_CACHE_DIR", str(ROOT / ".venv" / "cache"))).expanduser()
if not LOCAL_CACHE.is_absolute():
    LOCAL_CACHE = ROOT / LOCAL_CACHE
MODEL_CACHE = LOCAL_CACHE / "sentence-transformers"
os.environ.setdefault("HF_HOME", str(LOCAL_CACHE / "huggingface"))
os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(MODEL_CACHE))
os.environ.setdefault("TORCH_HOME", str(LOCAL_CACHE / "torch"))
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(LOCAL_CACHE / "ms-playwright"))
