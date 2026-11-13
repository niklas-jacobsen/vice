from __future__ import annotations

from typing import Protocol

import numpy as np

FASTEMBED_MODELS = {
    "bge-small": "BAAI/bge-small-en-v1.5",
    "minilm": "sentence-transformers/all-MiniLM-L6-v2",
    "nomic": "nomic-ai/nomic-embed-text-v1.5",
}
STATIC_MODELS = {"potion-8m": "minishlab/potion-base-8M", "potion-32m": "minishlab/potion-base-32M"}


def _normalize(m: np.ndarray) -> np.ndarray:
    m = np.asarray(m, dtype=np.float32)
    return m / np.clip(np.linalg.norm(m, axis=1, keepdims=True), 1e-12, None)


class Embedder(Protocol):
    name: str

    def embed_docs(self, texts: list[str]) -> np.ndarray: ...
    def embed_query(self, text: str) -> np.ndarray: ...


class FastEmbedEmbedder:
    """ONNX runtime models. fastembed applies each model's query/passage prefixes."""

    def __init__(self, name: str):
        from fastembed import TextEmbedding

        self.name = name
        self._m = TextEmbedding(FASTEMBED_MODELS[name])

    def embed_docs(self, texts):
        return _normalize(np.stack(list(self._m.passage_embed(texts))))

    def embed_query(self, text):
        return _normalize(np.stack(list(self._m.query_embed([text]))))[0]


class StaticEmbedder:
    """model2vec static embeddings: a table lookup and a mean, no transformer forward pass."""

    def __init__(self, name: str):
        from model2vec import StaticModel

        self.name = name
        self._m = StaticModel.from_pretrained(STATIC_MODELS[name])

    def embed_docs(self, texts):
        return _normalize(self._m.encode(texts))

    def embed_query(self, text):
        return _normalize(self._m.encode([text]))[0]


def make_embedder(name: str) -> Embedder:
    if name in FASTEMBED_MODELS:
        return FastEmbedEmbedder(name)
    if name in STATIC_MODELS:
        return StaticEmbedder(name)
    raise ValueError(f"unknown embedder {name!r}; options: {[*FASTEMBED_MODELS, *STATIC_MODELS]}")
