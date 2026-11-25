import os
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path


class Cancelled(RuntimeError):
    pass


def run(args: list[str], *, cwd: Path | None = None, timeout: float = 60,
        check_cancel: Callable[[], None] = lambda: None) -> str:
    check_cancel()
    try:
        with tempfile.TemporaryFile(dir=cwd) as stdout, tempfile.TemporaryFile(dir=cwd) as stderr:
            with subprocess.Popen(
                args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            ) as process:
                deadline = time.monotonic() + timeout
                try:
                    while process.poll() is None:
                        check_cancel()
                        if time.monotonic() >= deadline:
                            raise RuntimeError("Media command timed out")
                        time.sleep(0.2)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                if process.returncode:
                    stderr.seek(max(0, stderr.tell() - 2000))
                    detail = stderr.read().decode("utf-8", errors="replace").strip()
                    raise RuntimeError(f"{Path(args[0]).stem} exited with code {process.returncode}. {detail}")
                stdout.seek(0)
                return stdout.read().decode("utf-8", errors="replace")
    except FileNotFoundError as exc:
        raise RuntimeError(f"Could not start {Path(args[0]).name}. Check the executable configuration.") from exc
