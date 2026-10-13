"""Optional screenshot helper.

Screenshots are how a *human* checks a document; they are never part of the
build. The geometry validator runs without a browser, so a machine with no
Chrome/Edge installed still gets full automated checking — only ``--png`` and
``docforge shot`` degrade.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

try:                       # POSIX only; Windows falls back to no locking
    import fcntl
except ImportError:        # pragma: no cover
    fcntl = None

LOCK_PATH = Path(tempfile.gettempdir()) / "docforge-shot.lock"
LOCK_WAIT = 180.0
"""Seconds to wait for another docforge screenshot to finish.

Headless Chromium is memory-hungry, so running several at once on one machine
makes them all slow and eventually times them out. Screenshots are a
developer-facing nicety, not part of the build, so they queue instead of
competing.
"""

CANDIDATES = (
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/microsoft-edge",
    "/snap/bin/chromium",
)

FLAGS = (
    "--headless=new",
    "--no-sandbox",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--no-first-run",
    "--no-default-browser-check",
    "--hide-scrollbars",
    "--virtual-time-budget=6000",
)


class RenderError(Exception):
    pass


def find_browser(explicit: str = None):
    """Absolute path to a usable Chromium-family browser, or ``None``."""
    if explicit:
        return explicit if Path(explicit).is_file() else None
    env = os.environ.get("DOCFORGE_BROWSER")
    if env and Path(env).is_file():
        return env
    for path in CANDIDATES:
        if Path(path).is_file():
            return path
    for name in ("microsoft-edge", "google-chrome", "chromium", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return None


def available(explicit: str = None) -> bool:
    return find_browser(explicit) is not None


@contextlib.contextmanager
def _screenshot_lock(wait: float = LOCK_WAIT):
    """Serialise concurrent screenshots across processes."""
    if fcntl is None:
        yield True
        return
    fh = os.open(str(LOCK_PATH), os.O_CREAT | os.O_RDWR, 0o600)
    deadline = time.monotonic() + wait
    acquired = False
    try:
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.25)
        yield acquired
    finally:
        if acquired:
            with contextlib.suppress(OSError):
                fcntl.flock(fh, fcntl.LOCK_UN)
        os.close(fh)


def _kill_group(proc, grace: float = 10.0, pgid: int = None) -> None:
    """Kill a browser and everything it spawned.

    *pgid* should be the group captured when the process was started. Asking the
    OS for it here is too late in the common case: the group leader exits as
    soon as it has written the screenshot, `getpgid` then raises, and the helper
    processes -- which are what actually pile up and hold the GPU pipe --
    survive. Twenty-eight renders left fourteen of them behind.
    """
    try:
        os.killpg(pgid if pgid is not None else os.getpgid(proc.pid),
                  signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        with contextlib.suppress(OSError):
            proc.kill()
    try:
        proc.communicate(timeout=grace)
    except Exception:                                  # already gone, or wedged
        pass


def shot(html_path, png_path, width=1440, height=2400, scale=2.0,
         browser: str = None, timeout: int = 180, wait_for_lock: float = LOCK_WAIT) -> Path:
    """Screenshot *html_path* into *png_path*.

    ``height`` is the viewport height: the capture is from the top of the
    document, so pass something tall for a full-page grab.
    """
    exe = find_browser(browser)
    if not exe:
        raise RenderError(
            "no Chromium-family browser found; set DOCFORGE_BROWSER to its path "
            "or skip screenshots (they are optional)"
        )
    html_path = Path(html_path).resolve()
    png_path = Path(png_path).resolve()
    png_path.parent.mkdir(parents=True, exist_ok=True)
    if png_path.exists():
        png_path.unlink()
    with _screenshot_lock(wait_for_lock) as acquired:
        if not acquired:
            raise RenderError(
                "another docforge screenshot is still running; raise the wait "
                "or run them one at a time"
            )
        with tempfile.TemporaryDirectory(prefix="docforge-shot-") as profile:
            cmd = [exe, *FLAGS, f"--user-data-dir={profile}",
                   f"--force-device-scale-factor={scale:g}",
                   f"--window-size={int(width)},{int(height)}",
                   f"--screenshot={png_path}", f"file://{html_path}"]
            # A Chromium browser is a process *tree*. Killing only the direct
            # child on timeout leaves the helpers alive, and they hold the
            # profile and the GPU pipe — so the next run is slower, times out
            # too, and leaves more behind. Start a session and kill the group.
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    start_new_session=True)
            # Capture the group now, while the leader is certainly alive.
            pgid = None
            with contextlib.suppress(OSError):
                pgid = os.getpgid(proc.pid)
            try:
                proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                _kill_group(proc, pgid=pgid)
                raise RenderError(f"browser timed out after {timeout}s") from exc
            finally:
                # Chromium leaves helper processes behind when the main process
                # exits. The screenshot is already written by now, so sweep the
                # whole group: without this they accumulate, each holds a GPU
                # pipe, and a long run (28 figures) slows to a crawl against
                # processes it started itself.
                _kill_group(proc, grace=1.0, pgid=pgid)
    if not png_path.is_file():
        raise RenderError("browser produced no screenshot")
    return png_path


def shot_data_url(html: str, png_path, **kwargs) -> Path:
    """Screenshot raw HTML by writing it to a temp file first."""
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as fh:
        fh.write(html)
        tmp = fh.name
    try:
        return shot(tmp, png_path, **kwargs)
    finally:
        os.unlink(tmp)
