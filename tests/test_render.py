"""Screenshot plumbing — the parts that must not leak processes.

A timed-out Chromium leaves a whole process tree behind unless it is killed as a
group. The orphans hold the profile directory and the GPU pipe, so the next
screenshot is slower, times out too, and leaves more behind: one bad run turns
into a session where every capture times out.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest

from docforge import render as R


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@unittest.skipIf(sys.platform == "win32", "process groups are POSIX")
class KillGroupTest(unittest.TestCase):
    def setUp(self):
        self.proc = subprocess.Popen(
            ["bash", "-c", "sleep 300 & sleep 300"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        time.sleep(0.4)
        self.children = subprocess.run(
            ["pgrep", "-P", str(self.proc.pid)],
            capture_output=True, text=True).stdout.split()

    def tearDown(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=5)

    def test_the_whole_tree_dies_not_just_the_parent(self):
        self.assertTrue(self.children, "fixture spawned no children")
        R._kill_group(self.proc)
        self.proc.wait(timeout=5)
        for pid in self.children:
            self.assertFalse(_alive(int(pid)),
                             f"child {pid} survived the kill")

    def test_killing_an_already_dead_process_is_not_an_error(self):
        self.proc.kill()
        self.proc.wait(timeout=5)
        R._kill_group(self.proc)          # must not raise


class ShotContractTest(unittest.TestCase):
    def test_shot_uses_a_new_session_so_it_can_kill_the_group(self):
        import inspect
        src = inspect.getsource(R.shot)
        self.assertIn("start_new_session=True", src)
        self.assertIn("_kill_group(proc", src)
        # The group must be captured while the leader is alive: asking for it
        # after the process exits raises, and the helpers -- which are what pile
        # up -- are exactly the ones that then survive.
        self.assertIn("pgid = os.getpgid(proc.pid)", src)
        self.assertLess(src.index("pgid = os.getpgid(proc.pid)"),
                        src.index("proc.communicate(timeout=timeout)"),
                        "capture the group before waiting, not after")

    def test_a_missing_browser_is_reported_not_crashed(self):
        with self.assertRaises(R.RenderError):
            R.shot("whatever.html", "/tmp/nope.png",
                   browser="/nonexistent/browser", wait_for_lock=0.0)


if __name__ == "__main__":
    unittest.main()
