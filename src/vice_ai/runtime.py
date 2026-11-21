"""Wiring helpers shared by the CLI and the evaluation harness."""
from __future__ import annotations

import os
from pathlib import Path

from .config import ROOT, Config, load_dotenv
from .embed import make_embedder
from .jev import TypeSafeJudge
from .retrieve import Retriever
from .store import make_store
from .types import Block


def build_retriever(cfg: Config, blocks: list[Block]) -> Retriever:
    rt = Retriever(make_embedder(cfg.embedder), make_store(cfg.store), hybrid=cfg.hybrid, rrf_k=cfg.rrf_k)
    rt.index(blocks)
    rt.embedder.embed_query("warm up")  # first ONNX call is slow; pay it at start-up
    return rt


def build_judge(cfg: Config, cache: bool = False, read_cache: bool = True, payload_log: Path | None = None) -> TypeSafeJudge:
    load_dotenv()
    if not os.environ.get("TYPESAFE_API_KEY"):
        raise SystemExit("TYPESAFE_API_KEY is not set. Put it in a .env file at the repository root, or export it.")
    judge = TypeSafeJudge(cfg, cache_dir=ROOT / "data" / "jev_cache" if cache else None, payload_log=payload_log)
    judge.read_cache = read_cache
    return judge
