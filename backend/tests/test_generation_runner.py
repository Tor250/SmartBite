import asyncio
from threading import Event

import pytest

from app.generation_runner import GenerationBusy, GenerationRunner, GenerationTimedOut
from app.observability import request_id_context


def test_runner_requires_positive_limits():
    default_runner = GenerationRunner()
    assert default_runner._timeout_seconds == 30
    default_runner.shutdown()
    with pytest.raises(ValueError):
        GenerationRunner(max_concurrent=0)
    with pytest.raises(ValueError):
        GenerationRunner(timeout_seconds=0)


def test_runner_propagates_request_context_to_worker_thread():
    runner = GenerationRunner(max_concurrent=1)
    token = request_id_context.set("runner-trace-1")
    try:
        result = asyncio.run(runner.run(request_id_context.get))
    finally:
        request_id_context.reset(token)
        runner.shutdown()

    assert result == "runner-trace-1"


def test_runner_releases_slot_if_executor_rejects_submission():
    runner = GenerationRunner(max_concurrent=1)
    original_submit = runner._executor.submit

    def reject_submission(*_args, **_kwargs):
        raise RuntimeError("executor stopped")

    runner._executor.submit = reject_submission
    try:
        async def failed_submission():
            with pytest.raises(RuntimeError, match="executor stopped"):
                await runner.run(lambda: "unreachable")

        asyncio.run(failed_submission())
        runner._executor.submit = original_submit
        assert asyncio.run(runner.run(lambda: "slot released")) == "slot released"
    finally:
        runner._executor.submit = original_submit
        runner.shutdown()


def test_runner_rejects_excess_work_without_queueing():
    runner = GenerationRunner(max_concurrent=1, timeout_seconds=2)
    started = Event()
    release = Event()

    def blocking_call():
        started.set()
        release.wait(1)
        return "done"

    async def scenario():
        active = asyncio.create_task(runner.run(blocking_call))
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.005)
        assert started.is_set()
        with pytest.raises(GenerationBusy):
            await runner.run(lambda: "must not run")
        release.set()
        assert await active == "done"

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        runner.shutdown()


def test_runner_keeps_timed_out_work_slot_until_worker_exits():
    runner = GenerationRunner(max_concurrent=1, timeout_seconds=0.01)
    started = Event()
    release = Event()

    def blocking_call():
        started.set()
        release.wait(1)
        return "late result"

    async def scenario():
        active = asyncio.create_task(runner.run(blocking_call))
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.001)
        assert started.is_set()
        with pytest.raises(GenerationTimedOut):
            await active
        with pytest.raises(GenerationBusy):
            await runner.run(lambda: "must not run")
        release.set()
        for _ in range(100):
            try:
                return await runner.run(lambda: "new request")
            except GenerationBusy:
                await asyncio.sleep(0.005)
        pytest.fail("Worker did not release its slot after completion")

    try:
        assert asyncio.run(scenario()) == "new request"
    finally:
        release.set()
        runner.shutdown()


def test_runner_keeps_cancelled_work_slot_until_worker_exits():
    runner = GenerationRunner(max_concurrent=1, timeout_seconds=2)
    started = Event()
    release = Event()

    def blocking_call():
        started.set()
        release.wait(1)
        return "finished after client disconnect"

    async def scenario():
        active = asyncio.create_task(runner.run(blocking_call))
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.001)
        assert started.is_set()
        active.cancel()
        with pytest.raises(asyncio.CancelledError):
            await active
        with pytest.raises(GenerationBusy):
            await runner.run(lambda: "must not run")
        release.set()
        for _ in range(100):
            try:
                return await runner.run(lambda: "slot released")
            except GenerationBusy:
                await asyncio.sleep(0.005)
        pytest.fail("Worker did not release its slot after client cancellation")

    try:
        assert asyncio.run(scenario()) == "slot released"
    finally:
        release.set()
        runner.shutdown()
