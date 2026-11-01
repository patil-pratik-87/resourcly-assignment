import threading

from resourcly.adapters.thread_jobs import ThreadJobsAdapter


def test_jobs_run_one_at_a_time_lower_priority_first_then_in_order() -> None:
    jobs = ThreadJobsAdapter()
    gate, done = threading.Event(), threading.Event()
    ran: list[str] = []
    jobs.submit(gate.wait)  # holds the worker while the others queue up
    jobs.submit(lambda: ran.append("read a"), priority=1)
    jobs.submit(lambda: ran.append("route"), priority=0)
    jobs.submit(lambda: ran.append("read b"), priority=1)
    jobs.submit(done.set, priority=2)

    gate.set()
    done.wait(timeout=5)
    jobs.close()

    assert ran == ["route", "read a", "read b"]


def test_a_failing_job_is_logged_and_the_next_one_runs(caplog) -> None:
    jobs = ThreadJobsAdapter()
    done = threading.Event()

    def fail() -> None:
        raise RuntimeError("out of memory")

    jobs.submit(fail)
    jobs.submit(done.set)

    assert done.wait(timeout=5)
    jobs.close()
    assert "a background job failed" in caplog.text
