"""
Runs pipeline scripts (calibrate_zones.py, multi_camera_dashboard.py) as
background subprocesses so the portal can trigger them with a button click
instead of you opening a terminal. Each job gets a log file under logs/ that
the jobs page tails.

One job per name may run at a time — starting a job that's already running
returns its existing status instead of spawning a second copy.
"""

import subprocess
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)


class Job:
    def __init__(self, name, cmd):
        self.name = name
        self.cmd = cmd
        self.log_path = LOGS_DIR / f"{name}.log"
        self.process = None
        self.started_at = None
        self.ended_at = None
        self.lock = threading.Lock()

    def start(self):
        with self.lock:
            if self.is_running():
                return False
            self.started_at = time.time()
            self.ended_at = None
            log_f = open(self.log_path, "w")
            self.process = subprocess.Popen(
                self.cmd,
                cwd=PROJECT_ROOT,
                stdout=log_f,
                stderr=subprocess.STDOUT,
            )
            self._log_file = log_f
            return True

    def is_running(self):
        if self.process is None:
            return False
        if self.process.poll() is None:
            return True
        if self.ended_at is None:
            self.ended_at = time.time()
            try:
                self._log_file.close()
            except Exception:
                pass
        return False

    def stop(self):
        with self.lock:
            if self.is_running():
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                return True
            return False

    def status(self):
        running = self.is_running()
        if self.process is None:
            state = "never run"
        elif running:
            state = "running"
        else:
            state = "failed" if self.process.returncode not in (0, None) else "finished"
        return {
            "name": self.name,
            "cmd": " ".join(self.cmd),
            "state": state,
            "returncode": None if self.process is None else self.process.returncode,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
        }

    def tail(self, lines=200):
        if not self.log_path.exists():
            return ""
        with open(self.log_path, errors="replace") as f:
            content = f.readlines()
        return "".join(content[-lines:])


class JobManager:
    def __init__(self):
        self._jobs = {}
        self._lock = threading.Lock()

    def _make_job(self, name, cmd):
        with self._lock:
            if name not in self._jobs:
                self._jobs[name] = Job(name, cmd)
            return self._jobs[name]

    def start(self, name, cmd):
        job = self._make_job(name, cmd)
        started = job.start()
        return job, started

    def get(self, name):
        with self._lock:
            return self._jobs.get(name)

    def all_statuses(self):
        with self._lock:
            return [j.status() for j in self._jobs.values()]


manager = JobManager()

PYTHON = sys.executable


def start_calibrate_all():
    return manager.start("calibrate_all", [PYTHON, "calibrate_zones.py"])


def start_calibrate_camera(camera_id):
    return manager.start(f"calibrate_{camera_id}", [PYTHON, "calibrate_zones.py", camera_id])


def start_dashboard():
    # --no-display: this job runs headless (stdout redirected to a log
    # file, no display attached) — cv2.imshow/waitKey would error here
    # regardless of anything else, a pre-existing issue this flag fixes.
    return manager.start("dashboard", [PYTHON, "multi_camera_dashboard.py", "--no-display"])
