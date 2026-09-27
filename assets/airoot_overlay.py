"""Transparent Windows listening overlay for the Airoot voice app."""
from __future__ import annotations

import argparse
import math
import time
import json
import socket
import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QImage, QPainterPath, QRadialGradient
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

try:
    import sounddevice as sd
except ImportError:
    sd = None


PORT = 53873

# Logo geometry. Kept smaller than the source cells so the pre-scaled frames are
# a reduction, never an enlargement.
LOGO_WIDTH = 132
LOGO_HEIGHT = 92
LOGO_TOP = 16
# How much the logo grows at full voice level.
GROWTH = 0.10
BASE = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent))
SPRITESHEET = BASE / "airoot-spritesheet.png"
ICON = BASE / "airoot-icon.ico"


# Inputs that record what the speakers play rather than what is said. Metering
# one of these shows a flat line while the user is talking.
_LOOPBACK_HINTS = ("stereo mix", "what u hear", "wave out", "output mix",
                   "loopback", "rec. playback", "pc speaker")
_ALIAS_HINTS = ("sound mapper", "primary sound capture", "primary sound driver")


def default_input_device():
    """The Windows default input, unless it is a loopback; then a real mic."""
    if sd is None:
        return None
    try:
        devices = [(i, d) for i, d in enumerate(sd.query_devices())
                   if d.get("max_input_channels", 0) > 0]
        default = sd.default.device[0]
        names = dict(devices)
        if default in names and not _is_loopback(names[default]["name"]):
            return None
        usable = [(i, d) for i, d in devices
                  if not _is_loopback(d["name"]) and not _is_alias(d["name"])]
        if not usable:
            return None
        return min(usable, key=lambda e: (
            0 if "microphone" in e[1]["name"].lower() else 1, e[0]))[0]
    except Exception:
        return None


def _is_loopback(name: str) -> bool:
    return any(hint in str(name).lower() for hint in _LOOPBACK_HINTS)


def _is_alias(name: str) -> bool:
    return any(hint in str(name).lower() for hint in _ALIAS_HINTS)


def send_command(command: str) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        try:
            client.sendto(command.encode("ascii"), ("127.0.0.1", PORT))
            return True
        except OSError:
            return False


def load_frames(width: int, height: int) -> list[QPixmap]:
    """Cut the spritesheet and pre-scale it to the size actually drawn.

    The cells are 600x417 but display at roughly a quarter of that. Letting
    drawPixmap shrink them on every frame gives a single-pass filter at a ~4x
    reduction, which visibly breaks up the thin strokes in the logo. Scaling
    once up front is both sharper and cheaper per frame.
    """
    sheet = QPixmap(str(SPRITESHEET))
    if sheet.isNull() or sheet.width() != 6000 or sheet.height() != 2502:
        raise RuntimeError("Airoot animation spritesheet is missing or invalid")
    # Render at the largest size the growth animation reaches, so scaling up
    # never happens; smaller sizes then come from a mild, clean reduction.
    target_w = int(width * (1.0 + GROWTH))
    target_h = int(height * (1.0 + GROWTH))
    frames = []
    for index in range(60):
        cell = sheet.copy((index % 10) * 600, (index // 10) * 417, 600, 417)
        frames.append(
            cell.scaled(
                target_w,
                target_h,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        )
    return frames


class ListeningOverlay(QWidget):
    def __init__(self, udp_socket: socket.socket) -> None:
        super().__init__()
        self.udp_socket = udp_socket
        self.frames = load_frames(LOGO_WIDTH, LOGO_HEIGHT)
        self.frame_index = 0
        self.microphone = None
        self.audio_peak = 0.0
        self.level = 0.0
        self.drag_origin: QPoint | None = None
        self.status = "Listening"
        # True while the caller is transcribing rather than listening.
        self.busy = False
        # Which input to meter. None means the Windows default, which is wrong
        # whenever that default is a loopback ("Stereo Mix"): the bars would sit
        # still while the caller records speech from a real microphone. The
        # caller can pin the right one with "show <device>".
        self.device = default_input_device()

        self.setWindowTitle("Airoot Voice")
        # Never take keyboard focus: the voice app pastes into whatever window is
        # focused, so an overlay that activates itself would receive the dictation.
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(220, 200)
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - self.width() // 2, screen.bottom() - self.height() - 12)

        self.menu = QMenu(self)
        self.menu.addAction("Show Airoot", self.show_listening)
        self.menu.addAction("Hide", self.hide_listening)
        self.menu.addSeparator()
        self.menu.addAction("Quit", QApplication.quit)
        self.tray = QSystemTrayIcon(QIcon(str(ICON)), self)
        self.tray.setToolTip("Airoot Voice")
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.tray_activated)
        self.tray.show()

        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self.advance)
        self.animation_timer.start(67)
        self.commands_timer = QTimer(self)
        self.commands_timer.timeout.connect(self.read_commands)
        self.commands_timer.start(100)

    def tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_listening()

    def start_microphone(self) -> None:
        if self.microphone is not None:
            return
        if sd is None:
            self.status = "Mic unavailable"
            return
        try:
            def sample(indata, frames, time_info, status):
                # Read only; the UI timer smooths and displays this value.
                samples = indata[:, 0]
                rms = float((samples * samples).mean() ** 0.5)
                self.audio_peak = min(1.0, rms * 13)

            self.microphone = sd.InputStream(
                channels=1,
                samplerate=16000,
                blocksize=512,
                device=self.device,
                callback=sample,
            )
            self.microphone.start()
            self.status = "Listening"
        except Exception:
            self.microphone = None
            self.status = "Check microphone access"

    def stop_microphone(self) -> None:
        if self.microphone is not None:
            self.microphone.stop()
            self.microphone.close()
            self.microphone = None
        self.audio_peak = 0.0

    def show_listening(self) -> None:
        self.show()
        self.raise_()
        self.start_microphone()

    def hide_listening(self) -> None:
        self.stop_microphone()
        self.busy = False
        self.status = "Listening"
        self.hide()

    def read_commands(self) -> None:
        while True:
            try:
                payload, _ = self.udp_socket.recvfrom(256)
            except BlockingIOError:
                break
            command = payload.decode("ascii", errors="ignore").strip().lower()
            # "show 2" pins the meter to device 2, so the bars follow the same
            # microphone the caller is recording from.
            verb, _, argument = command.partition(" ")
            if verb in ("show", "listening"):
                if argument.strip().isdigit():
                    device = int(argument.strip())
                    if device != self.device:
                        self.stop_microphone()
                        self.device = device
                self.busy = False
                self.status = "Listening"
                self.show_listening()
            elif verb in ("transcribing", "busy"):
                # Release the microphone: the caller already has the audio.
                self.stop_microphone()
                self.busy = True
                self.status = "Transcribing"
                self.show()
                self.raise_()
            elif verb == "hide":
                self.hide_listening()
            elif command == "quit":
                QApplication.quit()

    def advance(self) -> None:
        self.frame_index = (self.frame_index + 1) % len(self.frames)
        self.level += (self.audio_peak - self.level) * 0.30
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        frame = self.frames[self.frame_index]
        scale = 1.0 + GROWTH * math.sqrt(max(0.0, self.level))
        width, height = LOGO_WIDTH * scale, LOGO_HEIGHT * scale
        # Grow about the centre so the logo does not drift as it reacts.
        bounds = QRectF(
            (self.width() - width) / 2,
            LOGO_TOP - (height - LOGO_HEIGHT) / 2,
            width,
            height,
        )
        painter.drawPixmap(bounds, frame, QRectF(0, 0, frame.width(), frame.height()))

        # Compact floating recording status, with live bars when speech is heard.
        pill = QRectF(self.width() / 2 - 84, self.height() - 35, 168, 28)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(17, 18, 23, 205))
        painter.drawRoundedRect(pill, 14, 14)

        # The dot marks work in progress, so it belongs to transcription only --
        # while listening the moving bars already show the overlay is live.
        text_left = pill.left() + 14
        if self.busy:
            painter.setBrush(QColor(255, 44, 88))
            painter.drawEllipse(QRectF(pill.left() + 12, pill.top() + 10, 8, 8))
            text_left = pill.left() + 27

        painter.setPen(QPen(QColor(248, 241, 244)))
        painter.setFont(QFont("Segoe UI", 10))
        painter.drawText(
            QRectF(text_left, pill.top(), pill.right() - 36 - text_left, pill.height()),
            Qt.AlignVCenter,
            self.status,
        )
        painter.setPen(Qt.NoPen)
        # Bars stay still during transcription: there is no live input then.
        for bar in range(3):
            h = 4 + (0.0 if self.busy else self.level) * (11 + bar * 3)
            painter.setBrush(QColor(255, 88, 118, 225))
            painter.drawRoundedRect(QRectF(pill.right() - 31 + bar * 6, pill.center().y() - h / 2, 3, h), 1.5, 1.5)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.drag_origin = event.globalPosition().toPoint() - self.pos()
        elif event.button() == Qt.RightButton:
            self.menu.exec(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event) -> None:
        if self.drag_origin is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_origin)

    def mouseReleaseEvent(self, event) -> None:
        self.drag_origin = None

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.hide_listening()

    def closeEvent(self, event) -> None:
        self.stop_microphone()
        event.accept()



class AirootOverlay(ListeningOverlay):
    """Keep the recording logo compact, gather into a pill, then fade away."""

    MORPH_SECONDS = 0.38
    FADE_SECONDS = 0.28

    def __init__(self, udp_socket):
        super().__init__(udp_socket)
        self.mode = "hidden"
        self.entered = time.monotonic()
        self.completed = False
        self.pending = "hide"
        self.dismiss_shape = 1.0
        self.animation_timer.setInterval(16)
        self.commands_timer.setInterval(30)

    def show_listening(self):
        if self.mode == "dismiss" or self.completed:
            self.pending = "show"
            return
        self.mode = "listening"
        self.completed = False
        self.pending = "hide"
        self.busy = False
        self.status = "Listening"
        self.setWindowOpacity(1)
        super().show_listening()

    def hide_listening(self):
        self.stop_microphone()
        self.pending = "hide"
        self.finish_transcribing()

    def begin_transcribing(self):
        if self.mode in ("gather", "transcribing"):
            return
        self.stop_microphone()
        self.mode = "gather"
        self.entered = time.monotonic()
        self.completed = False
        self.pending = "hide"
        self.busy = True
        self.status = "Transcribing..."
        self.setWindowOpacity(1)
        self.show()
        self.raise_()

    def finish_transcribing(self):
        if self.mode in ("hidden", "dismiss"):
            return
        self.completed = True
        # Even a fast result completes the logo-to-pill transition first.
        if self.mode != "gather":
            self.dismiss_shape = 0.0 if self.mode == "listening" else 1.0
            self.mode = "dismiss"
            self.entered = time.monotonic()

    def read_commands(self):
        while True:
            try:
                payload, _ = self.udp_socket.recvfrom(60000)
            except BlockingIOError:
                break
            command = payload.decode("utf-8", errors="replace").strip()
            if command.startswith("{"):
                try:
                    data = json.loads(command)
                    if isinstance(data, dict) and data.get("event") == "transcript":
                        # Completion is a signal only; never display result text.
                        self.finish_transcribing()
                except (ValueError, TypeError):
                    pass
                continue
            verb, _, argument = command.lower().partition(" ")
            if verb in ("show", "listening"):
                if argument.isdigit() and int(argument) != self.device:
                    self.stop_microphone()
                    self.device = int(argument)
                self.show_listening()
            elif verb in ("transcribing", "busy"):
                self.begin_transcribing()
            elif verb == "hide":
                self.hide_listening()
            elif verb == "quit":
                QApplication.quit()

    @staticmethod
    def ease(t):
        t = max(0.0, min(1.0, t))
        return t * t * (3 - 2 * t)

    def advance(self):
        now = time.monotonic()
        self.frame_index = int(now / .067) % len(self.frames)
        self.level += (self.audio_peak - self.level) * .1
        if self.mode == "gather" and now - self.entered >= self.MORPH_SECONDS:
            self.mode = "transcribing"
            if self.completed:
                self.dismiss_shape = 1.0
                self.mode = "dismiss"
                self.entered = now
        if self.mode == "dismiss":
            progress = self.ease((now - self.entered) / self.FADE_SECONDS)
            self.setWindowOpacity(1 - progress)
            if progress >= 1:
                resume = self.pending == "show"
                self.mode = "hidden"
                self.completed = False
                self.busy = False
                self.hide()
                if resume:
                    self.show_listening()
        if self.isVisible():
            self.update()

    def paintEvent(self, event):
        if self.mode == "hidden":
            return
        if self.mode == "listening" or (self.mode == "dismiss" and self.dismiss_shape == 0):
            return super().paintEvent(event)
        t = self.ease((time.monotonic() - self.entered) / self.MORPH_SECONDS) if self.mode == "gather" else 1.0
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        pill = QRectF(self.width() / 2 - 84, self.height() - 35, 168, 28)
        # The sprite settles toward the existing capsule as it fades. Window
        # geometry stays fixed so it never jumps, grows, or steals focus.
        if t < 1:
            frame = self.frames[self.frame_index]
            scale = (1 + GROWTH * math.sqrt(max(0.0, self.level))) * (1 - .75 * t)
            width, height = LOGO_WIDTH * scale, LOGO_HEIGHT * scale
            center_y = (LOGO_TOP + LOGO_HEIGHT / 2) * (1 - t) + pill.center().y() * t
            p.setOpacity(1 - t)
            p.drawPixmap(QRectF((self.width() - width) / 2, center_y - height / 2, width, height), frame, QRectF(frame.rect()))
        p.setOpacity(1)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(17, 18, 23, 205))
        p.drawRoundedRect(pill, 14, 14)
        p.setOpacity(t)
        p.setFont(QFont("Segoe UI", 10))
        p.setPen(QColor(248, 241, 244))
        p.drawText(pill, Qt.AlignCenter, "Transcribing...")
        p.end()



def main() -> int:
    parser = argparse.ArgumentParser(description="Airoot Windows voice overlay")
    # "start" launches hidden and waits for commands, so a caller can preload the
    # overlay and have it appear instantly on the first "show".
    parser.add_argument(
        "command", nargs="?", default="show",
        choices=("show", "listening", "hide", "quit", "start"),
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        image = QImage(str(SPRITESHEET))
        assert not image.isNull() and image.size().width() == 6000 and image.size().height() == 2502
        print(f"Airoot overlay: 60 transparent frames; microphone library: {sd is not None}")
        return 0

    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        udp_socket.bind(("127.0.0.1", PORT))
    except OSError:
        udp_socket.close()
        if args.command != "start":
            send_command(args.command)
        return 0
    if args.command in ("hide", "quit"):
        udp_socket.close()
        return 0
    udp_socket.setblocking(False)
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(QIcon(str(ICON)))
    overlay = AirootOverlay(udp_socket)
    if args.command != "start":
        overlay.show_listening()
    result = app.exec()
    overlay.stop_microphone()
    udp_socket.close()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
