import threading
import math
import struct
import winsound

from .utils import ensure_dir
from .config import (
    TONE_FREQ_HZ,
    TONE_WAV_DURATION_SEC,
    TONE_VOLUME,
    SAMPLE_RATE,
)


def _wrap_wav_header(pcm_data: bytes, sample_rate: int) -> bytes:
    data_size = len(pcm_data)
    riff_size = 36 + data_size
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        riff_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        sample_rate,
        sample_rate * 2,
        2,
        16,
        b"data",
        data_size,
    )
    return header + pcm_data


def generate_tone_wav_bytes(
    freq_hz: int,
    duration_sec: float,
    volume: float = 0.3,
    sample_rate: int = 44100,
) -> bytes:
    volume = max(0.0, min(1.0, float(volume)))
    n_samples = max(1, int(sample_rate * duration_sec))
    amplitude = int(32767 * volume)

    frames = bytearray()
    for i in range(n_samples):
        t = i / sample_rate
        sample = int(amplitude * math.sin(2.0 * math.pi * freq_hz * t))
        frames += struct.pack("<h", sample)

    return _wrap_wav_header(frames, sample_rate)


def ensure_tone_file(path: str) -> None:
    ensure_dir(path.rsplit("\\", 1)[0] if "\\" in path else path.rsplit("/", 1)[0])
    wav_bytes = generate_tone_wav_bytes(
        freq_hz=TONE_FREQ_HZ,
        duration_sec=TONE_WAV_DURATION_SEC,
        volume=TONE_VOLUME,
        sample_rate=SAMPLE_RATE,
    )
    with open(path, "wb") as f:
        f.write(wav_bytes)


class LoopingTone:
    def __init__(self, wav_path: str):
        self._path = wav_path
        self._lock = threading.Lock()
        self._playing = False

    def start(self) -> None:
        with self._lock:
            if self._playing:
                return
            winsound.PlaySound(
                self._path,
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP,
            )
            self._playing = True

    def stop(self) -> None:
        with self._lock:
            if not self._playing:
                return
            winsound.PlaySound(None, winsound.SND_PURGE)
            self._playing = False


def trigger_timer_end_sound() -> None:
    def _play_chime():
        notes = [523.25, 659.25, 784.00, 1046.50]
        duration_ms = 180
        duration_sec = duration_ms / 1000.0
        sample_rate = 44100
        volume_base = 0.5

        all_frames = bytearray()

        for freq in notes:
            n_samples = int(sample_rate * duration_sec)
            frames = bytearray()
            max_amp = int(32767 * volume_base)

            for i in range(n_samples):
                t = i / sample_rate
                envelope = 1.0 - (i / n_samples)
                sample_val = int(max_amp * envelope * math.sin(2.0 * math.pi * freq * t))
                frames += struct.pack("<h", sample_val)

            all_frames += frames

        wav_data = _wrap_wav_header(all_frames, sample_rate)
        winsound.PlaySound(wav_data, winsound.SND_MEMORY)

    threading.Thread(target=_play_chime, daemon=True).start()
