from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np

# The shipped embedder. Runs the same ONNX export and tokenizer that fastembed uses for
# sentence-transformers/all-MiniLM-L6-v2, pinned to one revision, so vectors (and the
# calibration fitted on them) do not change underneath a user.
MINILM_REPO = "Qdrant/all-MiniLM-L6-v2-onnx"
MINILM_REVISION = "d13954661f83248295ba75c1ed411eef3b7b936e"
MINILM_FILES = ("model.onnx", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "config.json")
MINILM_MAX_TOKENS = 256

# Experiment-only models; these need the `eval` extra (fastembed, model2vec).
FASTEMBED_MODELS = {
    "bge-small": "BAAI/bge-small-en-v1.5",
    "nomic": "nomic-ai/nomic-embed-text-v1.5",
}
STATIC_MODELS = {"potion-8m": "minishlab/potion-base-8M", "potion-32m": "minishlab/potion-base-32M"}
EMBEDDERS = ["minilm", *FASTEMBED_MODELS, *STATIC_MODELS]


def _normalize(m: np.ndarray) -> np.ndarray:
    m = np.asarray(m, dtype=np.float32)
    return m / np.clip(np.linalg.norm(m, axis=1, keepdims=True), 1e-12, None)


class Embedder(Protocol):
    name: str

    def embed_docs(self, texts: list[str]) -> np.ndarray: ...
    def embed_query(self, text: str) -> np.ndarray: ...


def models_dir() -> Path:
    from .paths import home

    return home() / "models"


def minilm_files(cache_dir: Path | None = None, only: tuple[str, ...] = MINILM_FILES) -> Path:
    """Download (once) and return the folder holding the pinned MiniLM files.

    The revision is a commit hash, so once cached the files load without network access.
    """
    from huggingface_hub import hf_hub_download
    from huggingface_hub.utils import logging as hf_logging

    hf_logging.set_verbosity_error()  # a public model; the "set HF_TOKEN" hint is noise
    cache = str(cache_dir or models_dir())
    paths = [hf_hub_download(MINILM_REPO, f, revision=MINILM_REVISION, cache_dir=cache) for f in only]
    return Path(paths[0]).parent


class MiniLMEmbedder:
    """all-MiniLM-L6-v2: BERT forward pass, mean pooling over real tokens, L2 normalisation.

    Matches fastembed's PooledNormalizedEmbedding: right truncation at 256 tokens,
    batch-longest right padding with [PAD], token_type_ids all zero, pooling summed in
    float64. No query or passage prefixes.
    """

    name = "minilm"
    batch_size = 256

    def __init__(self, model_dir: Path | None = None):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        d = model_dir or minilm_files()
        tok = Tokenizer.from_file(str(d / "tokenizer.json"))
        tok.enable_truncation(max_length=MINILM_MAX_TOKENS, direction="right")
        pad_id = tok.token_to_id("[PAD]")
        tok.enable_padding(direction="right", pad_id=pad_id, pad_type_id=0, pad_token="[PAD]")
        self._tok = tok
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        self._sess = ort.InferenceSession(str(d / "model.onnx"), opts, providers=["CPUExecutionProvider"])
        self._inputs = {i.name for i in self._sess.get_inputs()}

    def _embed(self, texts: list[str]) -> np.ndarray:
        enc = self._tok.encode_batch(texts)
        ids = np.array([e.ids for e in enc], dtype=np.int64)
        mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._inputs:
            feed["token_type_ids"] = np.zeros_like(ids)
        hidden = self._sess.run(None, feed)[0]
        summed = np.sum(hidden, axis=1, where=mask[:, :, None].astype(bool), dtype=np.float64)
        pooled = summed / np.maximum(mask.sum(axis=1, keepdims=True), 1e-9)
        norm = np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
        return (pooled / norm).astype(hidden.dtype)

    def embed_docs(self, texts):
        texts = list(texts)
        if not texts:
            return np.zeros((0, 384), dtype=np.float32)
        out = [self._embed(texts[i : i + self.batch_size]) for i in range(0, len(texts), self.batch_size)]
        return _normalize(np.concatenate(out))

    def embed_query(self, text):
        return _normalize(self._embed([text]))[0]


class FastEmbedEmbedder:
    """Other ONNX models, for experiments. fastembed applies each model's prefixes."""

    def __init__(self, name: str):
        try:
            from fastembed import TextEmbedding
        except ImportError as e:
            raise RuntimeError(f"embedder {name!r} needs the eval extra: pip install 'vice-ai[eval]'") from e

        self.name = name
        self._m = TextEmbedding(FASTEMBED_MODELS[name])

    def embed_docs(self, texts):
        return _normalize(np.stack(list(self._m.passage_embed(texts))))

    def embed_query(self, text):
        return _normalize(np.stack(list(self._m.query_embed([text]))))[0]


class StaticEmbedder:
    """model2vec static embeddings: a table lookup and a mean, no transformer forward pass."""

    def __init__(self, name: str):
        try:
            from model2vec import StaticModel
        except ImportError as e:
            raise RuntimeError(f"embedder {name!r} needs the eval extra: pip install 'vice-ai[eval]'") from e

        self.name = name
        self._m = StaticModel.from_pretrained(STATIC_MODELS[name])

    def embed_docs(self, texts):
        return _normalize(self._m.encode(texts))

    def embed_query(self, text):
        return _normalize(self._m.encode([text]))[0]


def make_embedder(name: str) -> Embedder:
    if name == "minilm":
        return MiniLMEmbedder()
    if name in FASTEMBED_MODELS:
        return FastEmbedEmbedder(name)
    if name in STATIC_MODELS:
        return StaticEmbedder(name)
    raise ValueError(f"unknown embedder {name!r}; options: {EMBEDDERS}")
