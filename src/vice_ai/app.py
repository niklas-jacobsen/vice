"""Assemble the running application from user settings."""
from __future__ import annotations

import asyncio
import sys

from . import ask, keys, paths, tracing
from .calibrate import Calibration, load_calibration
from .index import Index, SyncStats
from .jev import JudgeError, TypeSafeJudge
from .outputs import AGENT_OUTPUTS, AGENT_TRIGGERS, Dispatcher
from .pipeline import Pipeline
from .settings import Settings
from .types import AmbientEvent


def calibration_for(settings: Settings) -> Calibration:
    """Your own ~/.vice/calibration.json if present, otherwise the one shipped with vice."""
    user = paths.user_calibration()
    path = user if user.exists() else paths.DEFAULT_CALIBRATION
    return load_calibration(path, model=settings.pipeline.model)


class App:
    def __init__(self, settings: Settings, echo: bool = False):
        self.settings = settings
        self.cal = calibration_for(settings)
        self.cfg = self.cal.apply(settings.pipeline)
        self.index = Index(settings.sources, self.cfg)
        self.judge: TypeSafeJudge | None = None
        self.pipeline: Pipeline | None = None
        self.startup_skipped: list[str] = []
        self.dispatcher = Dispatcher(settings.outputs, echo=echo)

    async def start(self) -> SyncStats:
        key = keys.get()  # raises MissingKey with instructions
        self.judge = TypeSafeJudge(self.settings.pipeline, api_key=key)
        retriever, stats = await asyncio.to_thread(self.index.build)
        self.startup_skipped = stats.skipped_lines()
        self.pipeline = Pipeline(self.settings.pipeline, self.judge, retriever, self.cal)
        await self.judge.warm()
        return stats

    async def handle(self, event: AmbientEvent) -> dict:
        only = AGENT_OUTPUTS if event.trigger in AGENT_TRIGGERS else None
        return await self.dispatcher.emit(await self.pipeline.handle(event), only=only)

    async def resync(self) -> SyncStats | None:
        if not await asyncio.to_thread(self.index.changed):
            return None
        retriever, stats = await asyncio.to_thread(self.index.build)
        self.pipeline.retriever = retriever  # swapped whole, so an in-flight event sees one consistent index
        return stats

    async def close(self) -> None:
        if self.judge:
            await self.judge.aclose()

    async def serve(self) -> None:
        """Answer `vice ask` and `vice hook` over the socket and keep the index current until cancelled."""
        s = self.settings
        if s.tracing:
            tracing.configure()

        async def keep_warm() -> None:
            while True:
                await asyncio.sleep(self.cfg.keepalive_s * 0.5)
                try:
                    await self.judge.warm()
                except JudgeError:
                    pass  # the next real request will report it

        async def watch_sources() -> None:
            while True:
                await asyncio.sleep(s.resync_s)
                try:
                    if stats := await self.resync():
                        print(f"vice: sources changed; {stats.blocks} blocks ({stats.embedded} embedded)", file=sys.stderr, flush=True)
                        for line in stats.skipped_lines():
                            print(f"vice: {line}", file=sys.stderr, flush=True)
                except Exception as e:  # noqa: BLE001
                    print(f"vice: re-index failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)

        print(f"vice: serving on {paths.socket_file()}; {len(self.pipeline.retriever.blocks)} blocks; "
              f"model {self.cfg.model}", file=sys.stderr, flush=True)
        for line in self.startup_skipped:
            print(f"vice: {line}", file=sys.stderr, flush=True)
        await asyncio.gather(ask.serve(self.handle), keep_warm(), watch_sources())
