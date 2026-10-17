"""Bounded execution for blocking recipe generators."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from threading import BoundedSemaphore
from time import monotonic
from typing import Callable, TypeVar


T = TypeVar("T")
DEFAULT_GENERATION_TIMEOUT_SECONDS = 30


class GenerationBusy(RuntimeError):
    """All generator slots are occupied; no request was queued."""


class GenerationTimedOut(TimeoutError):
    """The generator exceeded the shared request time limit."""


class GenerationRunner:
    def __init__(self, max_concurrent: int = 4, timeout_seconds: float = DEFAULT_GENERATION_TIMEOUT_SECONDS):
        if max_concurrent < 1 or timeout_seconds <= 0:
            raise ValueError("Generator limits must be positive")
        self._slots = BoundedSemaphore(max_concurrent)
        self._executor = ThreadPoolExecutor(
            max_workers=max_concurrent,
            thread_name_prefix="smartbite-generator",
        )
        self._timeout_seconds = timeout_seconds

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True)

    async def run(self, function: Callable[..., T], *args: object) -> T:
        if not self._slots.acquire(blocking=False):
            raise GenerationBusy

        context = copy_context()
        try:
            future = self._executor.submit(context.run, function, *args)
        except BaseException:
            self._slots.release()
            raise

        # После тайм-аута вызывающий код не может остановить работающий поток. Освобождаем
        # его слот только после завершения задачи, чтобы тайм-ауты не создавали скрытую очередь.
        future.add_done_callback(lambda _future: self._slots.release())
        deadline = monotonic() + self._timeout_seconds
        while not future.done():
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise GenerationTimedOut
            # Опрос не привязывает общий исполнитель к одному циклу asyncio:
            # ASGI-приложение и тесты могут создавать новый цикл для каждого запроса.
            await asyncio.sleep(min(0.01, remaining))

        return future.result()
