import threading
import pystray
from PIL import Image, ImageDraw


class TrayController:
    def __init__(self, title: str, on_show, on_quit):
        self._title = title
        self._on_show = on_show
        self._on_quit = on_quit

        self._icon = None
        self._thread = None
        self._running = False

    def _make_icon_image(self) -> Image.Image:
        img = Image.new("RGB", (64, 64), color=(40, 40, 40))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle((10, 10, 54, 54), radius=10, fill=(200, 60, 60))
        draw.rectangle((26, 20, 38, 44), fill=(245, 245, 245))
        return img

    def ensure_running(self) -> None:
        if self._icon is not None and self._running:
            return

        def on_show(icon, item):
            self._on_show()

        def on_quit(icon, item):
            self._on_quit()

        menu = pystray.Menu(
            pystray.MenuItem("Show", on_show),
            pystray.MenuItem("Quit", on_quit),
        )

        self._icon = pystray.Icon("FocusGuardian", self._make_icon_image(), self._title, menu)

        def run_icon():
            self._running = True
            try:
                self._icon.run()
            finally:
                self._running = False

        self._thread = threading.Thread(target=run_icon, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._icon is None:
            return
        try:
            self._icon.stop()
        except Exception:
            pass
