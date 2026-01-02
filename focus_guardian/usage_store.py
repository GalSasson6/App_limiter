import os
import json
import threading

from .utils import ensure_dir, today_str


class UsageStore:
    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()
        self._date = today_str()
        self._usage: dict[str, float] = {}

    def load(self) -> None:
        ensure_dir(os.path.dirname(self._path))
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            with self._lock:
                self._date = str(data.get("date", today_str()))
                usage = data.get("usage", {}) or {}
                cleaned: dict[str, float] = {}
                for k, v in usage.items():
                    try:
                        cleaned[str(k).lower()] = float(v)
                    except Exception:
                        continue
                self._usage = cleaned
        except Exception:
            with self._lock:
                self._date = today_str()
                self._usage = {}
        self.reset_if_new_day()

    def save(self) -> None:
        ensure_dir(os.path.dirname(self._path))
        with self._lock:
            data = {"date": self._date, "usage": self._usage}
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def reset_if_new_day(self) -> None:
        t = today_str()
        with self._lock:
            if self._date != t:
                self._date = t
                self._usage = {}

    def add_seconds(self, proc_name: str, seconds: float) -> None:
        if not proc_name or seconds <= 0:
            return
        key = proc_name.lower()
        with self._lock:
            self._usage[key] = float(self._usage.get(key, 0.0)) + float(seconds)

    def get_seconds(self, proc_name: str) -> float:
        if not proc_name:
            return 0.0
        key = proc_name.lower()
        with self._lock:
            return float(self._usage.get(key, 0.0))

    def snapshot(self) -> tuple[str, dict[str, float]]:
        with self._lock:
            return self._date, dict(self._usage)
