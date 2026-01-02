import threading
import time
import math
import customtkinter as ctk

from .config import (
    APP_TITLE,
    APPDATA_DIR,
    DATA_FILE,
    GAME_FILE,
    TONE_FILE,
    POLL_INTERVAL_SEC,
    UI_UPDATE_MIN_INTERVAL_SEC,
    SAVE_EVERY_SEC,
    STRICT_MAX_PAUSES,
)
from .utils import ensure_dir, seconds_to_mmss
from .logging_setup import setup_logger
from .audio import (
    ensure_tone_file,
    LoopingTone,
    trigger_timer_end_sound,
    trigger_work_start_sound,
    trigger_break_reminder_sound,
)
from .usage_store import UsageStore
from .game_db import GameDB
from .process_monitor import get_foreground_pid, safe_process_name, TargetMatcher
from .tray import TrayController


ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class FocusGuardianApp:
    def __init__(self):
        ensure_dir(APPDATA_DIR)
        ensure_tone_file(TONE_FILE)

        self.logger = setup_logger()
        self.logger.info("App start")

        self.root = ctk.CTk()
        self.root.title(APP_TITLE)
        self.root.geometry("420x740")
        self.root.minsize(420, 740)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

        self._stop_event = threading.Event()
        self._monitor_enabled = ctk.BooleanVar(value=True)

        self._strict_active = False
        self._strict_paused = False
        self._strict_remaining_sec = 0.0
        self._strict_end_mono = 0.0
        self._strict_pause_count = 0
        self._break_paused = False  # NEW
        self._break_remaining_sec = 0.0  # NEW
        self._last_break_reminder_mono = 0.0  # NEW
        self._last_break_illegal_reminder_mono = 0.0
        self._last_pause_reminder_mono = 0.0
        # --- POMODORO VARIABLES ADDED HERE ---
        self._break_active = False
        self._break_end_mono = 0.0
        self._pomodoro_loop = False
        self._planned_focus_sec = 0.0
        self._planned_break_sec = 0.0
        # -------------------------------------

        self._last_ui_update = 0.0
        self._last_save_mono = 0.0

        self.store = UsageStore(DATA_FILE)
        self.store.load()

        self.game = GameDB(GAME_FILE, self.logger)
        self.game.load()

        self.matcher = TargetMatcher()
        self.tone = LoopingTone(TONE_FILE)

        self.tray = TrayController(
            title=APP_TITLE,
            on_show=self.show_from_tray,
            on_quit=self.quit_app,
        )

        self._build_ui()
        self._apply_defaults()

        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
    # UI
    def _build_ui(self) -> None:
        self.header = ctk.CTkLabel(self.root, text=APP_TITLE, font=("Roboto", 26, "bold"))
        self.header.pack(pady=(18, 8))

        self.frame_game = ctk.CTkFrame(self.root)
        self.frame_game.pack(padx=18, pady=(6, 10), fill="x")

        self.game_top = ctk.CTkLabel(self.frame_game, text="Game", font=("Arial", 16, "bold"))
        self.game_top.grid(row=0, column=0, sticky="w", padx=12, pady=(10, 4))

        self.reward_label = ctk.CTkLabel(self.frame_game, text="Reward: None", text_color="gray")
        self.reward_label.grid(row=0, column=1, sticky="e", padx=12, pady=(10, 4))

        self.today_score_label = ctk.CTkLabel(self.frame_game, text="Today score: 0", anchor="w")
        self.today_score_label.grid(row=1, column=0, sticky="w", padx=12, pady=2)

        self.session_xp_label = ctk.CTkLabel(self.frame_game, text="Session XP: 0", anchor="w")
        self.session_xp_label.grid(row=2, column=0, sticky="w", padx=12, pady=2)

        self.level_label = ctk.CTkLabel(self.frame_game, text="Level: 1 (XP 0)", anchor="w")
        self.level_label.grid(row=1, column=1, sticky="e", padx=12, pady=2)

        self.streak_label = ctk.CTkLabel(self.frame_game, text="Streak: 0 (best 0)", anchor="w")
        self.streak_label.grid(row=2, column=1, sticky="e", padx=12, pady=2)

        self.level_bar = ctk.CTkProgressBar(self.frame_game)
        self.level_bar.grid(row=3, column=0, columnspan=2, sticky="ew", padx=12, pady=(6, 10))
        self.level_bar.set(0.0)

        self.frame_game.grid_columnconfigure(0, weight=1)
        self.frame_game.grid_columnconfigure(1, weight=1)

        self.frame_targets = ctk.CTkFrame(self.root)
        self.frame_targets.pack(padx=18, pady=(6, 8), fill="x")

        ctk.CTkLabel(self.frame_targets, text="Target processes (illegal apps), comma-separated:").pack(
            anchor="w", padx=12, pady=(10, 4)
        )
        self.targets_entry = ctk.CTkEntry(self.frame_targets, placeholder_text="chrome.exe, discord.exe")
        self.targets_entry.pack(padx=12, pady=(0, 12), fill="x")

        self.frame_daily = ctk.CTkFrame(self.root)
        self.frame_daily.pack(padx=18, pady=8, fill="x")

        ctk.CTkLabel(self.frame_daily, text="Daily limit (minutes) per illegal app:").grid(
            row=0, column=0, sticky="w", padx=12, pady=12
        )
        self.daily_limit_entry = ctk.CTkEntry(self.frame_daily, width=90, justify="center")
        self.daily_limit_entry.grid(row=0, column=1, sticky="e", padx=12, pady=12)
        self.frame_daily.grid_columnconfigure(0, weight=1)

        # --- MODIFIED STRICT FRAME ---
        self.frame_strict = ctk.CTkFrame(self.root, fg_color="#3a2323")
        self.frame_strict.pack(padx=18, pady=8, fill="x")

        ctk.CTkLabel(self.frame_strict, text="Strict timer (study session) minutes:").grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 6)
        )
        self.strict_minutes_entry = ctk.CTkEntry(self.frame_strict, width=90, justify="center", placeholder_text="30")
        self.strict_minutes_entry.grid(row=0, column=1, sticky="e", padx=12, pady=(12, 6))

        # NEW: Break minutes entry
        ctk.CTkLabel(self.frame_strict, text="Break duration minutes:").grid(
            row=1, column=0, sticky="w", padx=12, pady=(0, 6)
        )
        self.break_minutes_entry = ctk.CTkEntry(self.frame_strict, width=90, justify="center", placeholder_text="5")
        self.break_minutes_entry.grid(row=1, column=1, sticky="e", padx=12, pady=(0, 6))

        # NEW: Pomodoro auto-loop switch
        self._pomodoro_var = ctk.BooleanVar(value=False)
        self.pomodoro_switch = ctk.CTkSwitch(
            self.frame_strict,
            text="Auto-loop (Pomodoro)",
            variable=self._pomodoro_var
        )
        self.pomodoro_switch.grid(row=2, column=0, columnspan=2, padx=12, pady=(0, 6), sticky="w")

        self.frame_strict.grid_columnconfigure(0, weight=1)

        self.strict_btn = ctk.CTkButton(
            self.frame_strict,
            text="Start strict timer",
            fg_color="#c0392b",
            hover_color="#e74c3c",
            command=self.start_strict_timer,
        )
        self.strict_btn.grid(row=3, column=0, columnspan=2, padx=12, pady=(6, 8), sticky="ew")

        self.pause_btn = ctk.CTkButton(
            self.frame_strict,
            text="Pause strict timer (0/2)",
            fg_color="#555555",
            hover_color="#777777",
            command=self.toggle_pause_strict_timer,
        )
        self.pause_btn.grid(row=4, column=0, columnspan=2, padx=12, pady=(0, 10), sticky="ew")

        self.stop_btn = ctk.CTkButton(
            self.frame_strict,
            text="Stop session",
            fg_color="#7f8c8d",
            hover_color="#95a5a6",
            command=self.stop_strict_timer,
        )
        self.stop_btn.grid(row=5, column=0, columnspan=2, padx=12, pady=(0, 10), sticky="ew")

        self.strict_status = ctk.CTkLabel(self.frame_strict, text="Strict timer: inactive", text_color="gray")
        self.strict_status.grid(row=6, column=0, columnspan=2, padx=12, pady=(0, 12), sticky="w")
        # -----------------------------

        self.frame_control = ctk.CTkFrame(self.root)
        self.frame_control.pack(padx=18, pady=8, fill="x")

        self.monitor_switch = ctk.CTkSwitch(
            self.frame_control,
            text="Monitoring enabled",
            variable=self._monitor_enabled,
            command=self._on_monitor_toggle,
        )
        self.monitor_switch.pack(anchor="w", padx=12, pady=(12, 6))

        self.status_line = ctk.CTkLabel(
            self.frame_control,
            text="Status: monitoring",
            text_color="#2ecc71",
            font=("Arial", 14, "bold"),
        )
        self.status_line.pack(anchor="w", padx=12, pady=(0, 12))

        self.frame_info = ctk.CTkFrame(self.root)
        self.frame_info.pack(padx=18, pady=8, fill="both", expand=True)

        self.active_app_label = ctk.CTkLabel(self.frame_info, text="Active app: (unknown)", anchor="w")
        self.active_app_label.pack(fill="x", padx=12, pady=(12, 4))

        self.focus_label = ctk.CTkLabel(self.frame_info, text="Illegal app focused: no", anchor="w")
        self.focus_label.pack(fill="x", padx=12, pady=4)

        self.limit_label = ctk.CTkLabel(self.frame_info, text="Daily limit: not reached", anchor="w")
        self.limit_label.pack(fill="x", padx=12, pady=4)

        ctk.CTkLabel(self.frame_info, text="Today illegal usage by app:", anchor="w").pack(
            fill="x", padx=12, pady=(10, 4)
        )
        self.usage_box = ctk.CTkTextbox(self.frame_info, height=140)
        self.usage_box.pack(fill="x", expand=False, padx=12, pady=(0, 10))
        self.usage_box.configure(state="disabled")

        ctk.CTkLabel(self.frame_info, text="Game statistics (today):", anchor="w").pack(
            fill="x", padx=12, pady=(0, 4)
        )
        self.game_stats_box = ctk.CTkTextbox(self.frame_info, height=160)
        self.game_stats_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.game_stats_box.configure(state="disabled")

        self.footer = ctk.CTkLabel(
            self.root,
            text='Tip: Click "X" to hide to tray. Use tray menu to show or quit.',
            text_color="gray",
        )
        self.footer.pack(pady=(0, 12))
    def _apply_defaults(self) -> None:
        if not self.targets_entry.get().strip():
            self.targets_entry.insert(0, "chrome.exe, discord.exe")
        if not self.daily_limit_entry.get().strip():
            self.daily_limit_entry.insert(0, "60")
        if not self.strict_minutes_entry.get().strip():
            self.strict_minutes_entry.insert(0, "30")
        if not self.break_minutes_entry.get().strip():
            self.break_minutes_entry.insert(0, "5")

        self.matcher.set_from_text(self.targets_entry.get())
        self._refresh_usage_box()
        self._refresh_game_ui()
        self._update_pause_button_text()
        self._update_stop_button_state()

    def _on_monitor_toggle(self) -> None:
        enabled = bool(self._monitor_enabled.get())
        self.logger.info(f"Monitoring toggled enabled={enabled}")
        if not enabled:
            self.tone.stop()
        self._safe_ui_update_status_line(enabled)

    def _safe_ui_update_status_line(self, enabled: bool) -> None:
        def _do():
            if enabled:
                self.status_line.configure(text="Status: monitoring", text_color="#2ecc71")
            else:
                self.status_line.configure(text="Status: paused", text_color="red")
        self.root.after(0, _do)

    def start_strict_timer(self) -> None:
        try:
            mins = float(self.strict_minutes_entry.get().strip())
            break_mins = float(self.break_minutes_entry.get().strip())  # NEW
            if mins <= 0:
                return
        except Exception:
            return

        total_sec = mins * 60.0

        # --- NEW SETUP ---
        self._planned_focus_sec = total_sec
        self._planned_break_sec = break_mins * 60.0
        self._pomodoro_loop = self._pomodoro_var.get()
        self._break_active = False
        self._break_paused = False
        self._break_remaining_sec = 0.0
        self._last_break_reminder_mono = 0.0
        self._last_break_illegal_reminder_mono = 0.0
        self._last_pause_reminder_mono = 0.0
        # -----------------

        self._strict_active = True
        self._strict_paused = False
        self._strict_remaining_sec = total_sec
        self._strict_end_mono = time.monotonic() + total_sec
        self._strict_pause_count = 0
        self._update_pause_button_text()
        self._update_stop_button_state()

        self.game.start_session(total_sec)
        # ... rest of function stays the same ...
        if not self._monitor_enabled.get():
            self._monitor_enabled.set(True)
            self._safe_ui_update_status_line(True)

        self.logger.info(f"Strict timer started mins={mins}")

    def _update_pause_button_text(self) -> None:
        def _do():
            if self._break_active:
                self.pause_btn.configure(state="normal")
                if self._break_paused:
                    self.pause_btn.configure(text="Resume Break")
                else:
                    self.pause_btn.configure(text="Pause Break")
                return

            if not self._strict_active:
                self.pause_btn.configure(
                    text=f"Pause strict timer (0/{STRICT_MAX_PAUSES})",
                    state="disabled",
                )
                return

            state = "normal"
            if self._strict_pause_count >= STRICT_MAX_PAUSES and not self._strict_paused:
                state = "disabled"
            label = (
                "Resume strict timer"
                if self._strict_paused
                else f"Pause strict timer ({self._strict_pause_count}/{STRICT_MAX_PAUSES})"
            )
            self.pause_btn.configure(text=label, state=state)

        self.root.after(0, _do)

    def _update_stop_button_state(self) -> None:
        def _do():
            if self._strict_active or self._break_active:
                self.stop_btn.configure(state="normal")
            else:
                self.stop_btn.configure(state="disabled")

        self.root.after(0, _do)

    def stop_strict_timer(self) -> None:
        if not self._strict_active and not self._break_active:
            return

        self._strict_active = False
        self._strict_paused = False
        self._strict_remaining_sec = 0.0
        self._strict_pause_count = 0
        self._break_active = False
        self._break_paused = False
        self._break_remaining_sec = 0.0
        self._last_break_reminder_mono = 0.0
        self._last_break_illegal_reminder_mono = 0.0
        self._last_pause_reminder_mono = 0.0

        self.tone.stop()

        if self.game.is_session_active():
            self.game.end_session("stopped")

        self._update_pause_button_text()
        self._update_stop_button_state()
        self.logger.info("Strict/break session stopped")

    def toggle_pause_strict_timer(self) -> None:
        if self._break_active:
            if self._break_paused:
                self._break_paused = False
                self._break_end_mono = time.monotonic() + self._break_remaining_sec
                self._last_break_reminder_mono = time.monotonic()
                self._update_pause_button_text()
                self.logger.info("Break resumed")
            else:
                self._break_paused = True
                now = time.monotonic()
                self._break_remaining_sec = max(0.0, self._break_end_mono - now)
                self._last_break_reminder_mono = now
                self._update_pause_button_text()
                self.logger.info("Break paused")
            return

        if not self._strict_active:
            return

        if self._strict_paused:
            self._strict_paused = False
            self._strict_end_mono = time.monotonic() + max(0.0, self._strict_remaining_sec)
            self._update_pause_button_text()
            self.logger.info("Strict resumed")
            return

        if self._strict_pause_count >= STRICT_MAX_PAUSES:
            self._update_pause_button_text()
            return

        now = time.monotonic()
        remaining = self._strict_end_mono - now
        self._strict_remaining_sec = max(0.0, remaining)
        self._strict_paused = True
        self._strict_pause_count += 1
        self._last_pause_reminder_mono = now
        self._update_pause_button_text()

        self.game.note_pause_used()
        self.logger.info(f"Strict paused pause_count={self._strict_pause_count}")

    # Tray
    def hide_to_tray(self) -> None:
        self.logger.info("Hide to tray")
        self.tray.ensure_running()
        self.root.withdraw()

    def show_from_tray(self) -> None:
        self.logger.info("Show from tray")

        def _do():
            try:
                self.root.deiconify()
                self.root.lift()
                self.root.focus_force()
            except Exception:
                pass

        self.root.after(0, _do)

    def quit_app(self) -> None:
        self.logger.info("Quit requested")
        self._stop_event.set()
        self.tone.stop()
        self.store.save()
        self.game.save()

        if self._strict_active and self.game.is_session_active():
            self.game.end_session("quit")

        def _do():
            try:
                self.tray.stop()
                self.root.destroy()
            except Exception:
                pass

        self.root.after(0, _do)

    # Monitor loop
    def _read_daily_limit_seconds(self) -> float:
        try:
            mins = float(self.daily_limit_entry.get().strip())
            if mins <= 0:
                return float("inf")
            return mins * 60.0
        except Exception:
            return float("inf")

    def _refresh_usage_box(self) -> None:
        date_str, usage = self.store.snapshot()
        lines = [f"Date: {date_str}", ""]
        if not usage:
            lines.append("(no illegal usage recorded yet)")
        else:
            items = sorted(usage.items(), key=lambda kv: kv[1], reverse=True)
            for proc, sec in items:
                lines.append(f"{proc}  |  {seconds_to_mmss(sec)}")
        content = "\n".join(lines)

        def _do():
            self.usage_box.configure(state="normal")
            self.usage_box.delete("1.0", "end")
            self.usage_box.insert("1.0", content)
            self.usage_box.configure(state="disabled")

        self.root.after(0, _do)

    def _refresh_game_ui(self) -> None:
        snap = self.game.snapshot_today()
        day = snap.get("day", {})
        lt = snap.get("lifetime", {})
        active = snap.get("active")

        totals = (day.get("totals") or {})
        today_points = int(totals.get("points", 0))

        lvl, xp, prog = GameDB.level_progress(lt)
        cur_streak = int(lt.get("current_streak", 0))
        best_streak = int(lt.get("best_streak", 0))

        session_xp = 0
        reward = "None"
        if active:
            tmp_pts, tmp_reward = self.game._compute_points(active)
            session_xp = int(tmp_pts)
            reward = tmp_reward
        else:
            sessions = (day.get("sessions") or [])
            if sessions:
                reward = sessions[-1].get("reward", "None")

        study_sec = float(totals.get("study_sec", 0.0))
        illegal_sec = float(totals.get("illegal_sec", 0.0))
        break_sec = float(totals.get("break_sec", 0.0))

        sessions = (day.get("sessions") or [])
        last5 = sessions[-5:]

        stats_lines = [
            f"Today points: {today_points}",
            f"Study: {seconds_to_mmss(study_sec)}",
            f"Illegal: {seconds_to_mmss(illegal_sec)}",
            f"Breaks: {seconds_to_mmss(break_sec)}",
            "",
            "Last sessions:",
        ]
        if not last5:
            stats_lines.append("(none yet)")
        else:
            for s in reversed(last5):
                pts = int(s.get("points", 0))
                rew = s.get("reward", "None")
                st = seconds_to_mmss(float(s.get("study_sec", 0.0)))
                il = seconds_to_mmss(float(s.get("illegal_sec", 0.0)))
                br = seconds_to_mmss(float(s.get("break_sec", 0.0)))
                stats_lines.append(f"- {pts} pts | {rew} | study {st} | illegal {il} | break {br}")

        stats_text = "\n".join(stats_lines)

        def _do():
            self.reward_label.configure(text=f"Reward: {reward}")
            self.today_score_label.configure(text=f"Today score: {today_points}")
            self.session_xp_label.configure(text=f"Session XP: {session_xp}")
            self.level_label.configure(text=f"Level: {lvl} (XP {xp})")
            self.streak_label.configure(text=f"Streak: {cur_streak} (best {best_streak})")
            self.level_bar.set(prog)

            self.game_stats_box.configure(state="normal")
            self.game_stats_box.delete("1.0", "end")
            self.game_stats_box.insert("1.0", stats_text)
            self.game_stats_box.configure(state="disabled")

        self.root.after(0, _do)

    def _set_labels(
        self,
        active_proc: str | None,
        illegal_focused: bool,
        strict_text: str,
        limit_text: str,
        status_color: str | None = None,
    ) -> None:
        active_display = active_proc or "(unknown)"

        def _do():
            self.active_app_label.configure(text=f"Active app: {active_display}")
            self.focus_label.configure(text=f"Illegal app focused: {'yes' if illegal_focused else 'no'}")
            self.strict_status.configure(
                text=strict_text,
                text_color=("#e74c3c" if "active" in strict_text.lower() else "gray"),
            )
            self.limit_label.configure(text=limit_text)
            if status_color is not None:
                self.status_line.configure(text_color=status_color)

        self.root.after(0, _do)

    def _monitor_loop(self) -> None:
        last_tick = time.monotonic()
        self._last_save_mono = last_tick
        last_targets_text = None
        prev_illegal_focus = False

        while not self._stop_event.is_set():
            now = time.monotonic()
            dt = now - last_tick
            last_tick = now

            self.store.reset_if_new_day()
            self.game.reset_if_new_day()

            # ... (targets text logic same as before) ...

            try:
                targets_text = self.targets_entry.get()
            except Exception:
                targets_text = ""
            if targets_text != last_targets_text:
                last_targets_text = targets_text
                self.matcher.set_from_text(targets_text)
                self.logger.info(f"Targets updated: {targets_text}")

            enabled = bool(self._monitor_enabled.get())
            strict_remaining = 0.0

            if self._strict_active:
                # === FOCUS SESSION ===
                if self._strict_paused:
                    strict_remaining = max(0.0, self._strict_remaining_sec)
                    self.game.add_break(dt, reason="paused")
                    if (now - self._last_pause_reminder_mono) >= 60.0:
                        trigger_break_reminder_sound()
                        self._last_pause_reminder_mono = now
                else:
                    strict_remaining = self._strict_end_mono - now
                    if strict_remaining <= 0:
                        # Focus Finished
                        self._strict_active = False
                        self._strict_paused = False
                        strict_remaining = 0.0
                        self._strict_pause_count = 0
                        self._update_pause_button_text()

                        trigger_timer_end_sound()
                        if self.game.is_session_active():
                            self.game.end_session("completed")

                        if self._pomodoro_loop:
                            # Start Break
                            self._break_active = True
                            self._break_paused = False
                            self._break_end_mono = now + self._planned_break_sec
                            self._break_remaining_sec = self._planned_break_sec
                            self._last_break_reminder_mono = now  # Reset reminder timer
                            self._last_break_illegal_reminder_mono = now
                            self._last_pause_reminder_mono = 0.0
                            self._update_pause_button_text()  # Update button to "Pause Break"
                            self.logger.info("Pomodoro: Focus done, starting break")
                        else:
                            self._strict_remaining_sec = 0.0
                    else:
                        self._strict_remaining_sec = max(0.0, strict_remaining)

            elif self._break_active:
                # === BREAK SESSION ===
                if self._break_paused:
                    # Do not countdown, use stored remaining time
                    if (now - self._last_break_reminder_mono) >= 60.0:
                        trigger_break_reminder_sound()
                        self._last_break_reminder_mono = now
                else:
                    break_remaining = self._break_end_mono - now
                self._break_remaining_sec = max(0.0, break_remaining)

                    if break_remaining <= 0:
                        # Break Finished -> Restart Focus
                        trigger_work_start_sound()
                        self._break_active = False
                        self._break_paused = False
                        self._last_break_illegal_reminder_mono = 0.0

                        self._strict_active = True
                        self._strict_paused = False
                        self._strict_remaining_sec = self._planned_focus_sec
                        self._strict_end_mono = now + self._planned_focus_sec
                        self._strict_pause_count = 0
                        self._update_pause_button_text()

                        self.game.start_session(self._planned_focus_sec)
                        self.logger.info("Pomodoro: Break done, restarting focus")

            # Update Status Text
            if self._break_active:
                if self._break_paused:
                    strict_text = f"Pomodoro Break: PAUSED ({seconds_to_mmss(self._break_remaining_sec)} left)"
                else:
                    rem = max(0.0, self._break_remaining_sec)
                    strict_text = f"Pomodoro Break: {seconds_to_mmss(rem)} left"
            elif not self._strict_active:
                strict_text = "Strict timer: inactive"
            else:
                if self._strict_paused:
                    strict_text = f"Strict timer: paused ({seconds_to_mmss(strict_remaining)} left)"
                else:
                    strict_text = f"Strict timer: active ({seconds_to_mmss(strict_remaining)} left)"

            # ... (Rest of function for active_proc, match_key, limit_sec, etc. stays the same) ...
            # Ensure you include the rest of the original _monitor_loop code below here

            active_proc = None
            match_key = None
            illegal_focused = False

            if enabled:
                active_pid = get_foreground_pid()
                active_proc = safe_process_name(active_pid)
                match_key = self.matcher.match_key(active_proc)
                illegal_focused = match_key is not None

                if (
                    self._break_active
                    and (not self._break_paused)
                    and illegal_focused
                    and (now - self._last_break_illegal_reminder_mono) >= 30.0
                ):
                    trigger_break_reminder_sound()
                    self._last_break_illegal_reminder_mono = now

                if illegal_focused and dt > 0 and match_key:
                    self.store.add_seconds(match_key, dt)
            else:
                if self._strict_active and not self._strict_paused:
                    self.game.add_break(dt, reason="monitor_disabled")

            if self._strict_active and (not self._strict_paused):
                if enabled:
                    self.game.update_illegal_switch(illegal_focused)
                    if illegal_focused:
                        self.game.add_illegal(dt, active_proc)
                    else:
                        self.game.add_study(dt)
                else:
                    self.game.update_illegal_switch(False)

            limit_sec = self._read_daily_limit_seconds()
            reached = False
            limit_text = "Daily limit: (focus an illegal app to see its counter)"

            if math.isfinite(limit_sec):
                if illegal_focused and match_key:
                    used_sec = self.store.get_seconds(match_key)
                    reached = used_sec >= limit_sec
                    if reached:
                        limit_text = f"Daily limit: REACHED ({seconds_to_mmss(used_sec)})"
                    else:
                        limit_text = f"Daily limit: {seconds_to_mmss(used_sec)} / {seconds_to_mmss(limit_sec)}"
            else:
                limit_text = "Daily limit: disabled/invalid"

            strict_counts_as_active = self._strict_active and (not self._strict_paused)
            should_punish = enabled and illegal_focused and (strict_counts_as_active or reached)

            if should_punish:
                try:
                    self.tone.start()
                except Exception:
                    pass
            else:
                self.tone.stop()

            if enabled and illegal_focused != prev_illegal_focus:
                prev_illegal_focus = illegal_focused
                if illegal_focused:
                    self.logger.info(f"Illegal focus ENTER app={active_proc}")
                else:
                    self.logger.info("Illegal focus EXIT")

            if (now - self._last_ui_update) >= UI_UPDATE_MIN_INTERVAL_SEC:
                self._last_ui_update = now
                status_color = "red" if should_punish else "#2ecc71"

                if self._break_active:
                    status_color = "#3498db"

                self._set_labels(
                    active_proc=active_proc,
                    illegal_focused=illegal_focused,
                    strict_text=strict_text,
                    limit_text=limit_text,
                    status_color=status_color,
                )
                self._refresh_usage_box()
                self._refresh_game_ui()
                self._update_pause_button_text()
                self._update_stop_button_state()

            if (now - self._last_save_mono) >= SAVE_EVERY_SEC:
                self._last_save_mono = now
                self.store.save()
                self.game.save()

            time.sleep(POLL_INTERVAL_SEC)

        self.tone.stop()
        self.store.save()
        self.game.save()
        self.logger.info("App stopped")

    def run(self) -> None:
        self.root.mainloop()
