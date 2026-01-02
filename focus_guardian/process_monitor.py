import ctypes
import psutil


user32 = ctypes.windll.user32


def get_foreground_pid() -> int | None:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = ctypes.c_ulong(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value or None


def safe_process_name(pid: int | None) -> str | None:
    if not pid:
        return None
    try:
        return psutil.Process(pid).name()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None
    except Exception:
        return None


class TargetMatcher:
    def __init__(self):
        self._patterns: list[str] = []

    def set_from_text(self, text: str) -> None:
        tokens = [t.strip() for t in (text or "").split(",")]
        self._patterns = [t.lower() for t in tokens if t.strip()]

    def match_key(self, proc_name: str | None) -> str | None:
        if not proc_name:
            return None
        pn = proc_name.lower()
        for pat in self._patterns:
            if "*" in pat:
                parts = [p for p in pat.split("*") if p]
                if not parts:
                    continue
                idx = 0
                ok = True
                for part in parts:
                    found = pn.find(part, idx)
                    if found < 0:
                        ok = False
                        break
                    idx = found + len(part)
                if ok:
                    return pn
            elif "." in pat:
                if pn == pat:
                    return pn
            else:
                if pat in pn:
                    return pn
        return None
