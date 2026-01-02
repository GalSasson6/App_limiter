import os
import datetime


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def seconds_to_mmss(seconds: float) -> str:
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"


def today_str() -> str:
    return str(datetime.date.today())


def yesterday_str() -> str:
    return str(datetime.date.today() - datetime.timedelta(days=1))
