import os

APP_TITLE = "Focus Guardian"
APPDATA_DIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), "FocusGuardian")

DATA_FILE = os.path.join(APPDATA_DIR, "usage.json")
GAME_FILE = os.path.join(APPDATA_DIR, "game_db.json")

LOG_DIR = os.path.join(APPDATA_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "focus_guardian.log")

TONE_FILE = os.path.join(APPDATA_DIR, "tone.wav")

POLL_INTERVAL_SEC = 0.20
UI_UPDATE_MIN_INTERVAL_SEC = 0.35
SAVE_EVERY_SEC = 10.0

TONE_FREQ_HZ = 2500
TONE_WAV_DURATION_SEC = 0.12
TONE_VOLUME = 0.35
SAMPLE_RATE = 44100

STRICT_MAX_PAUSES = 2

# Game scoring
POINTS_PER_STUDY_MIN = 10
PENALTY_PER_ILLEGAL_10SEC = 5
PENALTY_PER_BREAK_MIN = 8
BONUS_NO_ILLEGAL = 50
BONUS_LOW_BREAKS = 20
BONUS_NO_PAUSES = 10
LOW_BREAKS_SEC = 120

XP_PER_POINT = 1
LEVEL_XP_UNIT = 500
