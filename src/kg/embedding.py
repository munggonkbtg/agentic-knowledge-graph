"""Block and query embeddings (config `embedding`, multilingual-e5-large).

Needs the `embed` dependency group (sentence-transformers, CPU torch); imported
lazily so the rest of the package works without it. Vectors are normalized
(cosine = dot product) and cached in data/cache/ by the SHA-256 of the prefixed
text and the model name, the same cache the M4/M5 evaluations use.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from kg.config import EmbeddingSettings


class Embedder:
    def __init__(self, settings: EmbeddingSettings, cache_dir: Path = Path("data/cache")) -> None:
        from sentence_transformers import SentenceTransformer

        t = time.time()
        self.settings = settings
        self.model = SentenceTransformer(settings.model, device=settings.device)
        self.load_seconds = time.time() - t
        self.encode_seconds = 0.0
        self.encoded = 0
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.path = cache_dir / f"{settings.model.replace('/', '__')}.json"
        self.cache = json.loads(self.path.read_text()) if self.path.exists() else {}

    def embed(self, texts: list[str], kind: str) -> list[list[float]]:
        """kind = 'query' or 'passage' (e5 prefixes)."""
        prefix = self.settings.query_prefix if kind == "query" else self.settings.passage_prefix
        prefixed = [f"{prefix}{t}" for t in texts]
        keys = [hashlib.sha256(p.encode()).hexdigest() for p in prefixed]
        todo = [(k, p) for k, p in zip(keys, prefixed) if k not in self.cache]
        if todo:
            t = time.time()
            vecs = self.model.encode([p for _, p in todo], batch_size=16,
                                     normalize_embeddings=True, show_progress_bar=False)
            self.encode_seconds += time.time() - t
            self.encoded += len(todo)
            for (k, _), v in zip(todo, vecs):
                self.cache[k] = [round(float(x), 6) for x in v]
            self.path.write_text(json.dumps(self.cache))
        return [self.cache[k] for k in keys]
