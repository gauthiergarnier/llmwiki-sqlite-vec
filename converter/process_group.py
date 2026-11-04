"""Subprocess helpers that keep child process trees killable on timeout."""

import contextlib
import os
import signal
import subprocess


def run_in_process_group(command: list[str], timeout: int, what: str) -> None:
    """Run a command in its own process group; kill the whole group on timeout."""
    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        _, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as e:
        _kill_process_group(proc)
        raise TimeoutError(f"{what} timed out after {timeout}s") from e
    if proc.returncode != 0:
        raise RuntimeError(f"{what} failed: {stderr.decode(errors='replace')[:500]}")


def _kill_process_group(proc: subprocess.Popen) -> None:
    """SIGKILL an entire process group, then reap the leader."""
    with contextlib.suppress(ProcessLookupError):
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    proc.wait()
