"""Offline tests for the worker loop (ADR 0014): the first production caller of
`Scheduler` and `TaskLedger`. No real agent, no network, no sleeping."""

import pytest

from stigdev.eventstore import SqliteEventStore
from stigdev.executor import ExecutionRequest, ExecutionResult, ExecutionUsage
from stigdev.node import MOBILE_M4, RESOURCE_CLASSES, HostFacts
from stigdev.scheduler import Budget, Reservation, Scheduler
from stigdev.workerd import WorkerLoop, WorkerLoopError, task_payload
from stigdev.workspace import WorkspaceRef

WORKSPACE = {"backend_id": "fake-backend", "workspace_id": "ws-1", "locator": "/tmp/ws-1"}


class RecordingExecutor:
    """Deterministic stand-in for a coding agent."""

    executor_id = "fake-agent/v1"

    def __init__(self, status: str = "success", usage: ExecutionUsage | None = None, raises=None):
        self.status, self.usage, self.raises = status, usage, raises
        self.seen: list[ExecutionRequest] = []

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        self.seen.append(request)
        if self.raises is not None:
            raise self.raises
        return ExecutionResult(
            attempt_id=request.attempt_id,
            workspace=request.workspace,
            status=self.status,  # type: ignore[arg-type]
            started_at=1.0,
            finished_at=2.0,
            exit_code=0 if self.status == "success" else 1,
            usage=self.usage or ExecutionUsage(input_tokens=3, output_tokens=4, usd=0.0),
        )


def store(tmp_path) -> SqliteEventStore:
    return SqliteEventStore.create(tmp_path / "store", store_id="test-store")


def scheduler(st, **kw) -> Scheduler:
    budget = kw.pop("budget", Budget(max_concurrency=1, max_usd=0.0))
    return Scheduler(st, run_id="run-1", budget=budget, started_at=0.0, **kw)


def iter_clock(start: float = 10.0, step: float = 1.0):
    state = {"t": start}

    def now() -> float:
        state["t"] += step
        return state["t"]

    return now


def loop(sched, executor, **kw) -> WorkerLoop:
    base = dict(scheduler=sched, executor=executor, holder="mobile-m4/worker-0", clock=iter_clock())
    base.update(kw)
    return WorkerLoop(**base)


def submit(sched, task_id: str = "t1", **payload_kw):
    payload = task_payload(instruction="do the thing", workspace=WORKSPACE, **payload_kw)
    return sched.submit(task_id, reservation=Reservation(calls=1), payload=payload)


# --- the loop -----------------------------------------------------------------


def test_a_leased_task_reaches_the_executor_and_is_finished(tmp_path):
    st = store(tmp_path)
    sched = scheduler(st)
    submit(sched)
    agent = RecordingExecutor()
    done = loop(sched, agent).tick()
    assert done is True
    assert [r.task_id for r in agent.seen] == ["t1"]
    assert sched.state().tasks["t1"].status == "succeeded"


def test_the_request_carries_the_lease_identity_not_an_invented_one(tmp_path):
    st = store(tmp_path)
    sched = scheduler(st)
    submit(sched)
    agent = RecordingExecutor()
    loop(sched, agent).tick()
    request = agent.seen[0]
    assert request.run_id == "run-1" and request.task_id == "t1"
    assert request.executor_id == "fake-agent/v1"
    assert request.workspace == WorkspaceRef(**WORKSPACE)
    assert request.instruction == "do the thing"


def test_an_idle_queue_is_not_an_error(tmp_path):
    st = store(tmp_path)
    agent = RecordingExecutor()
    assert loop(scheduler(st), agent).tick() is False
    assert agent.seen == []


def test_a_failing_agent_is_recorded_not_raised(tmp_path):
    st = store(tmp_path)
    sched = scheduler(st)
    submit(sched)
    loop(sched, RecordingExecutor(status="failed")).tick()
    assert sched.state().tasks["t1"].status in ("failed", "pending")


def test_an_executor_that_throws_finishes_the_lease_instead_of_leaking_it(tmp_path):
    st = store(tmp_path)
    sched = scheduler(st)
    submit(sched)
    loop(sched, RecordingExecutor(raises=RuntimeError("adapter blew up"))).tick()
    # the lease must not stay held: a crashed adapter is a finished attempt
    assert sched.state().tasks["t1"].status != "leased"


def test_run_until_idle_drains_the_queue_and_stops(tmp_path):
    st = store(tmp_path)
    sched = scheduler(st, budget=Budget(max_concurrency=1, max_usd=0.0))
    for i in range(3):
        submit(sched, task_id=f"t{i}")
    agent = RecordingExecutor()
    ticks = loop(sched, agent).run_until_idle(max_ticks=10)
    assert ticks == 3 and len(agent.seen) == 3


def test_run_until_idle_refuses_to_spin_forever(tmp_path):
    st = store(tmp_path)
    sched = scheduler(st)
    for i in range(5):
        submit(sched, task_id=f"t{i}")
    assert loop(sched, RecordingExecutor()).run_until_idle(max_ticks=2) == 2


# --- payload contract ----------------------------------------------------------


def test_a_task_without_an_instruction_fails_the_task_rather_than_the_worker(tmp_path):
    st = store(tmp_path)
    sched = scheduler(st)
    sched.submit("t1", reservation=Reservation(calls=1), payload={"workspace": WORKSPACE})
    agent = RecordingExecutor()
    assert loop(sched, agent).tick() is True
    assert agent.seen == []
    assert sched.state().tasks["t1"].status == "failed"


def test_task_payload_refuses_to_build_something_the_loop_cannot_run():
    with pytest.raises(WorkerLoopError):
        task_payload(instruction="", workspace=WORKSPACE)
    with pytest.raises(WorkerLoopError):
        task_payload(instruction="x", workspace={"backend_id": "b"})
    with pytest.raises(WorkerLoopError):
        task_payload(instruction="x", workspace=WORKSPACE, timeout_seconds=0)


# --- node admission at the acquire seam ----------------------------------------


def test_a_machine_under_memory_pressure_takes_no_new_work(tmp_path):
    st = store(tmp_path)
    sched = scheduler(st)
    submit(sched)
    agent = RecordingExecutor()
    worker = loop(
        sched,
        agent,
        profile=MOBILE_M4,
        resource_class=RESOURCE_CLASSES["text_small"],
        host_facts=lambda: HostFacts(memory_pressure="red", free_disk_gb=100.0),
    )
    assert worker.tick() is False
    assert agent.seen == [], "admission is checked before the task is leased"
    assert sched.state().tasks["t1"].status == "pending"


def test_a_calm_machine_admits_the_work(tmp_path):
    st = store(tmp_path)
    sched = scheduler(st)
    submit(sched)
    agent = RecordingExecutor()
    worker = loop(
        sched,
        agent,
        profile=MOBILE_M4,
        resource_class=RESOURCE_CLASSES["text_small"],
        host_facts=lambda: HostFacts(memory_pressure="green", free_disk_gb=100.0),
    )
    assert worker.tick() is True
    assert len(agent.seen) == 1


def test_the_laptop_refuses_a_class_it_could_never_host(tmp_path):
    """MOBILE_M4 has 16 GB usable; the coder class wants 28 GB. Fail at
    construction, not after a task has already been leased."""
    st = store(tmp_path)
    with pytest.raises(WorkerLoopError, match="never"):
        loop(
            scheduler(st),
            RecordingExecutor(),
            profile=MOBILE_M4,
            resource_class=RESOURCE_CLASSES["text_coder"],
        )
