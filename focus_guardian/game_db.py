import os
import json
import time
import math
import threading
import datetime
import logging

from .utils import ensure_dir, today_str, yesterday_str
from .config import (
    POINTS_PER_STUDY_MIN,
    PENALTY_PER_ILLEGAL_10SEC,
    PENALTY_PER_BREAK_MIN,
    BONUS_NO_ILLEGAL,
    BONUS_LOW_BREAKS,
    BONUS_NO_PAUSES,
    LOW_BREAKS_SEC,
    XP_PER_POINT,
    LEVEL_XP_UNIT,
)


class GameDB:
    def __init__(self, path: str, logger: logging.Logger):
        self._path = path
        self._logger = logger
        self._lock = threading.RLock()
        self._db = {
            "schema": 1,
            "days": {},
            "lifetime": {
                "xp": 0,
                "level": 1,
                "best_streak": 0,
                "current_streak": 0,
                "last_streak_date": None,
                "total_sessions": 0,
            },
        }

        self._active = None
        self._last_illegal_flag = False

    def load(self) -> None:
        ensure_dir(os.path.dirname(self._path))
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                with self._lock:
                    self._db = data
        except Exception:
            self._logger.exception("GameDB load failed, starting fresh")
        self._ensure_today_nodes()

    def save(self) -> None:
        ensure_dir(os.path.dirname(self._path))
        try:
            with self._lock:
                data = self._db
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            self._logger.exception("GameDB save failed")

    def _ensure_today_nodes(self) -> None:
        t = today_str()
        with self._lock:
            days = self._db.setdefault("days", {})
            if t not in days:
                days[t] = {
                    "sessions": [],
                    "totals": {
                        "study_sec": 0.0,
                        "illegal_sec": 0.0,
                        "break_sec": 0.0,
                        "points": 0,
                    },
                }

    def reset_if_new_day(self) -> None:
        self._ensure_today_nodes()

    def start_session(self, planned_sec: float) -> None:
        self.reset_if_new_day()
        with self._lock:
            self._active = {
                "id": int(time.time()),
                "date": today_str(),
                "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "ended_at": None,
                "planned_sec": float(planned_sec),
                "study_sec": 0.0,
                "illegal_sec": 0.0,
                "break_sec": 0.0,
                "pauses_used": 0,
                "illegal_switches": 0,
                "illegal_by_app": {},
                "notes": [],
                "points": 0,
                "reward": "None",
            }
            self._last_illegal_flag = False
        self._logger.info(f"GAME session start planned_sec={planned_sec:.1f}")

    def is_session_active(self) -> bool:
        with self._lock:
            return self._active is not None

    def note_pause_used(self) -> None:
        with self._lock:
            if self._active is None:
                return
            self._active["pauses_used"] = int(self._active.get("pauses_used", 0)) + 1

    def add_break(self, sec: float, reason: str | None = None) -> None:
        if sec <= 0:
            return
        with self._lock:
            if self._active is None:
                return
            self._active["break_sec"] = float(self._active.get("break_sec", 0.0)) + float(sec)
            if reason:
                self._active["notes"].append(f"break:{reason}")

    def add_study(self, sec: float) -> None:
        if sec <= 0:
            return
        with self._lock:
            if self._active is None:
                return
            self._active["study_sec"] = float(self._active.get("study_sec", 0.0)) + float(sec)

    def add_illegal(self, sec: float, proc: str | None) -> None:
        if sec <= 0:
            return
        with self._lock:
            if self._active is None:
                return
            self._active["illegal_sec"] = float(self._active.get("illegal_sec", 0.0)) + float(sec)
            if proc:
                key = proc.lower()
                d = self._active.setdefault("illegal_by_app", {})
                d[key] = float(d.get(key, 0.0)) + float(sec)

    def update_illegal_switch(self, illegal_flag: bool) -> None:
        with self._lock:
            if self._active is None:
                self._last_illegal_flag = illegal_flag
                return
            if illegal_flag and not self._last_illegal_flag:
                self._active["illegal_switches"] = int(self._active.get("illegal_switches", 0)) + 1
            self._last_illegal_flag = illegal_flag

    def _compute_points(self, s: dict) -> tuple[int, str]:
        study_sec = float(s.get("study_sec", 0.0))
        illegal_sec = float(s.get("illegal_sec", 0.0))
        break_sec = float(s.get("break_sec", 0.0))
        pauses = int(s.get("pauses_used", 0))

        pts = 0
        pts += int(study_sec // 60) * POINTS_PER_STUDY_MIN
        pts -= int(illegal_sec // 10) * PENALTY_PER_ILLEGAL_10SEC
        pts -= int(break_sec // 60) * PENALTY_PER_BREAK_MIN

        if illegal_sec <= 0.0:
            pts += BONUS_NO_ILLEGAL
        if break_sec <= LOW_BREAKS_SEC:
            pts += BONUS_LOW_BREAKS
        if pauses == 0:
            pts += BONUS_NO_PAUSES

        if pts < 0:
            pts = 0

        if illegal_sec <= 0.0 and break_sec <= 120 and pauses <= 1:
            reward = "Gold"
        elif illegal_sec <= 30 and break_sec <= 300:
            reward = "Silver"
        else:
            reward = "Bronze"

        return pts, reward

    def _update_level(self) -> None:
        lt = self._db.setdefault("lifetime", {})
        xp = int(lt.get("xp", 0))
        if xp < 0:
            xp = 0
        level = 1 + int(math.sqrt(xp / LEVEL_XP_UNIT)) if LEVEL_XP_UNIT > 0 else 1
        lt["level"] = int(max(1, level))
        lt["xp"] = xp

    def _update_streak(self, points_added: int) -> None:
        if points_added <= 0:
            return

        lt = self._db.setdefault("lifetime", {})
        last = lt.get("last_streak_date")
        today = today_str()

        if last == today:
            return

        if last == yesterday_str():
            lt["current_streak"] = int(lt.get("current_streak", 0)) + 1
        else:
            lt["current_streak"] = 1

        lt["last_streak_date"] = today
        best = int(lt.get("best_streak", 0))
        cur = int(lt.get("current_streak", 0))
        if cur > best:
            lt["best_streak"] = cur

    def end_session(self, reason: str) -> None:
        # Ensure day exists before we take the lock for the main update
        self.reset_if_new_day()

        with self._lock:
            s = self._active
            self._active = None
            self._last_illegal_flag = False

        if s is None:
            return

        s["ended_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        s["notes"].append(f"end:{reason}")

        points, reward = self._compute_points(s)
        s["points"] = int(points)
        s["reward"] = reward

        with self._lock:
            day = self._db["days"][today_str()]
            day["sessions"].append(s)

            totals = day["totals"]
            totals["study_sec"] = float(totals.get("study_sec", 0.0)) + float(s.get("study_sec", 0.0))
            totals["illegal_sec"] = float(totals.get("illegal_sec", 0.0)) + float(s.get("illegal_sec", 0.0))
            totals["break_sec"] = float(totals.get("break_sec", 0.0)) + float(s.get("break_sec", 0.0))
            totals["points"] = int(totals.get("points", 0)) + int(points)

            lt = self._db.setdefault("lifetime", {})
            lt["total_sessions"] = int(lt.get("total_sessions", 0)) + 1
            lt["xp"] = int(lt.get("xp", 0)) + int(points * XP_PER_POINT)

            self._update_streak(int(points))
            self._update_level()

        self._logger.info(
            f"GAME session end reason={reason} points={points} reward={reward} "
            f"study={s.get('study_sec', 0):.1f} illegal={s.get('illegal_sec', 0):.1f} break={s.get('break_sec', 0):.1f}"
        )

    def snapshot_today(self) -> dict:
        self._ensure_today_nodes()
        with self._lock:
            day = self._db["days"].get(today_str(), {})
            lt = self._db.get("lifetime", {})
            active = self._active
            return {
                "day": json.loads(json.dumps(day)),
                "lifetime": json.loads(json.dumps(lt)),
                "active": json.loads(json.dumps(active)) if active else None,
            }

    @staticmethod
    def level_progress(lifetime: dict) -> tuple[int, int, float]:
        xp = int(lifetime.get("xp", 0))
        lvl = int(lifetime.get("level", 1))
        prev = int(((lvl - 1) ** 2) * LEVEL_XP_UNIT)
        nxt = int((lvl ** 2) * LEVEL_XP_UNIT)
        denom = max(1, nxt - prev)
        prog = (xp - prev) / denom
        if prog < 0.0:
            prog = 0.0
        if prog > 1.0:
            prog = 1.0
        return lvl, xp, prog
