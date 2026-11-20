"""Optional local multilingual dense retrieval; no external embedding API/key."""
import json
import os
import threading
from .config import DATA, MODEL_CACHE
from .search import connect

_cache = None
_model_lock = threading.RLock()


def similarity_scores(vectors, vector):
    import numpy as np
    matrix = np.asarray(vectors, dtype=np.float32)
    query = np.asarray(vector, dtype=np.float32)
    if matrix.ndim != 2 or query.ndim != 1 or matrix.shape[1] != query.shape[0]:
        raise RuntimeError("Embedding dimensions do not match. Rebuild the semantic index.")
    if not np.isfinite(query).all():
        raise RuntimeError("The embedding model returned non-finite query values.")
    # Explicit reduction avoids the local BLAS matmul warnings observed with
    # valid, normalized memory-mapped float32 vectors on this Mac/NumPy build.
    scores = np.einsum('ij,j->i', matrix, query, optimize=False, dtype=np.float32)
    if not np.isfinite(scores).all():
        raise RuntimeError("Semantic scores are invalid. Rebuild the semantic index.")
    return np.clip(scores, -1.0, 1.0)


def build_semantic(model_name=None):
    import numpy as np
    from sentence_transformers import SentenceTransformer
    model_name = model_name or os.getenv("SEMANTIC_MODEL") or "intfloat/multilingual-e5-small"
    model = SentenceTransformer(model_name, cache_folder=str(MODEL_CACHE), trust_remote_code=False)
    with connect() as con:
        rows = [dict(r) for r in con.execute("SELECT * FROM chunks")]
    vectors = model.encode(["passage: "+r["title"]+"\n"+r["text"] for r in rows], normalize_embeddings=True, batch_size=24, show_progress_bar=True)
    dest = DATA / "semantic"
    dest.mkdir(exist_ok=True)
    np.save(dest / "vectors.npy", vectors)
    (dest / "chunks.json").write_text(json.dumps({"model": model_name, "chunks": rows}, ensure_ascii=False))
    return {"model": model_name, "chunks": len(rows)}


def semantic_retrieve(query, source=None):
    # A single embedding model instance bounds memory under concurrent requests.
    with _model_lock:
        return _semantic_retrieve(query, source)


def _semantic_retrieve(query, source=None):
    global _cache
    if not os.getenv("SEMANTIC_MODEL") or not (DATA / "semantic/chunks.json").exists():
        return []
    import numpy as np
    from sentence_transformers import SentenceTransformer
    if _cache is None:
        meta = json.loads((DATA / "semantic/chunks.json").read_text())
        # Query-time retrieval must use already downloaded weights. Installation
        # and first download belong to setup/embed, not an interactive chat turn.
        model = SentenceTransformer(meta["model"], cache_folder=str(MODEL_CACHE), local_files_only=True, trust_remote_code=False)
        vectors = np.load(DATA / "semantic/vectors.npy", mmap_mode="r")
        if vectors.ndim != 2 or vectors.shape[0] != len(meta["chunks"]) or not np.isfinite(vectors).all():
            raise RuntimeError("The semantic index is inconsistent. Rebuild it with app embed.")
        _cache = (meta, model, vectors)
    meta, model, vectors = _cache
    vector = model.encode(["query: "+query], normalize_embeddings=True)[0]
    scores = similarity_scores(vectors, vector)
    ranked = np.argsort(scores)[::-1]
    results = []
    with connect() as con:
        for i in ranked:
            row = meta["chunks"][int(i)]
            if source and row["source"] != source:
                continue
            # Ignore deleted/replaced index chunks after a new CSV ingest.
            if not con.execute("SELECT 1 FROM chunks WHERE id=?", (row["id"],)).fetchone():
                continue
            results.append({**row, "retrieval_score": float(scores[i])})
            if len(results) == 5:
                break
    return results
