import itertools
import logging
import queue
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)


class ThreadJobsAdapter:
    """Runs jobs one at a time on one background thread: lower priority first, then in order.

    One thread, so a read never competes with another for the machine; a vision-language reader
    holds one model in memory. A job that raises is logged and the next one runs. Jobs still
    waiting at close are dropped.
    """

    def __init__(self) -> None:
        self._queue: queue.PriorityQueue = queue.PriorityQueue()
        self._order = itertools.count()
        self._thread = threading.Thread(target=self._work, name="resourcly-jobs", daemon=True)
        self._thread.start()

    def submit(self, job: Callable[[], None], priority: int = 0) -> None:
        self._queue.put((priority, next(self._order), job))

    def close(self) -> None:
        self._queue.put((-1, next(self._order), None))
        # A read can take minutes; the thread is a daemon, so the process need not wait for it.
        self._thread.join(timeout=2)

    def _work(self) -> None:
        while True:
            _, _, job = self._queue.get()
            if job is None:
                return
            try:
                job()
            except Exception:
                log.exception("a background job failed")
