"""Benchmark executions in a separate process, with a timeout that is
enforced: a call that runs too long has its process killed, instead of
being found too slow once it ends.
"""

from collections.abc import Callable
import multiprocessing
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
import os
import traceback
from types import TracebackType
from typing import Any, TypeVar

T = TypeVar("T")
R = TypeVar("R")


class ExecutionTimeout(Exception):
    """A call did not finish in time; its process was killed."""


class WorkerFailed(Exception):
    """A call raised an error, or its process died."""


def _serve(connection: Connection, cpu: int | None) -> None:
    """Child process: run calls one at a time until told to stop."""
    if cpu is not None:
        os.sched_setaffinity(0, {cpu})
    while True:
        message = connection.recv()
        if message is None:
            return
        function, argument = message
        try:
            reply: tuple[str, Any] = ("ok", function(argument))
        except BaseException:
            reply = ("error", traceback.format_exc())
        connection.send(reply)


class IsolatedWorker:
    """
    One child process that runs calls one at a time, so a process stays
    warm across the executions of a scenario. A call that takes longer
    than `timeout` seconds kills the process; the next call starts a new
    one. The child is started with `spawn`, so it shares no state with
    the parent. `cpu` pins it to one CPU.
    """

    def __init__(self, timeout: float, cpu: int | None = None) -> None:
        self.timeout = timeout
        self.cpu = cpu
        self._context = multiprocessing.get_context("spawn")
        self._process: BaseProcess | None = None
        self._connection: Connection | None = None

    def call(self, function: Callable[[T], R], argument: T) -> R:
        """`function(argument)` in the child; both must be picklable."""
        connection = self._start()
        connection.send((function, argument))
        if not connection.poll(self.timeout):
            self._kill()
            raise ExecutionTimeout(
                f"No result within {self.timeout:g} s; process killed."
            )
        try:
            status, value = connection.recv()
        except EOFError:
            self._kill()
            raise WorkerFailed("The worker process died.") from None
        if status != "ok":
            raise WorkerFailed(value)
        result: R = value
        return result

    def close(self) -> None:
        if self._connection is not None and self._process is not None:
            try:
                self._connection.send(None)
            except OSError:
                pass
            self._process.join(timeout=5)
        self._kill()

    def __enter__(self) -> "IsolatedWorker":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def _start(self) -> Connection:
        if self._connection is not None:
            return self._connection
        parent, child = self._context.Pipe()
        process = self._context.Process(
            target=_serve, args=(child, self.cpu), daemon=True
        )
        process.start()
        child.close()
        self._process = process
        self._connection = parent
        return parent

    def _kill(self) -> None:
        if self._process is not None:
            if self._process.is_alive():
                self._process.kill()
            self._process.join()
            self._process.close()
            self._process = None
        if self._connection is not None:
            self._connection.close()
            self._connection = None
