"""Killable native work with wall-time, RSS, concurrency and temporary-file bounds."""

import multiprocessing
import os
import tempfile
import time
import psutil
from backend.reports.errors import ReportError


def _worker(connection, target, args, temporary_dir):
    tempfile.tempdir = temporary_dir
    os.environ["TMP"] = os.environ["TEMP"] = temporary_dir
    try:
        connection.send(("ok", target(*args)))
    except ReportError as exc:
        connection.send(("error", exc.code, str(exc), exc.status_code))
    except BaseException:
        connection.send(
            (
                "error",
                "processing_failed",
                "Document or retrieval processing failed safely.",
                422,
            )
        )
    finally:
        connection.close()


def run_isolated(target, args, timeout, memory_mb):
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    with tempfile.TemporaryDirectory(prefix="corecare-report-") as temporary_dir:
        process = context.Process(
            target=_worker, args=(child, target, args, temporary_dir), daemon=True
        )
        children = []
        deadline = time.monotonic() + max(0, timeout)
        try:
            try:
                process.start()
            except OSError:
                raise ReportError(
                    "worker_unavailable", "Isolated processing could not start.", 503
                ) from None
            child.close()
            try:
                monitored = psutil.Process(process.pid)
            except psutil.NoSuchProcess:
                monitored = None
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ReportError(
                        "processing_timeout",
                        "Report processing exceeded its time limit.",
                        504,
                    )
                if parent.poll(min(remaining, 0.05)):
                    message = parent.recv()
                    if message[0] == "error":
                        raise ReportError(message[1], message[2], message[3])
                    return message[1]
                try:
                    if monitored is None:
                        continue
                    children = monitored.children(recursive=True)
                    rss = sum(
                        p.memory_info().rss
                        for p in [monitored, *children]
                        if p.is_running()
                    )
                    if rss > memory_mb * 1024 * 1024:
                        raise ReportError(
                            "memory_limit",
                            "Report processing exceeded its memory limit.",
                            413,
                        )
                except psutil.NoSuchProcess:
                    pass
        except EOFError:
            raise ReportError(
                "processing_failed", "Report worker exited without a result."
            ) from None
        finally:
            parent.close()
            child.close()
            if process.pid is not None:
                try:
                    children = [
                        *children,
                        *psutil.Process(process.pid).children(recursive=True),
                    ]
                except psutil.NoSuchProcess:
                    pass
                # Kill OCR subprocesses too; parent owns their temporary directory.
                for descendant in children:
                    try:
                        descendant.kill()
                    except psutil.NoSuchProcess:
                        pass
                psutil.wait_procs(children, timeout=2)
                if process.is_alive():
                    process.terminate()
                process.join(timeout=2)
                if process.is_alive():
                    process.kill()
                    process.join()
