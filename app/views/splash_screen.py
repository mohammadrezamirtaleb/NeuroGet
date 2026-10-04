import os
import sys
from PyQt5.QtWidgets import QWidget, QApplication, QGraphicsDropShadowEffect
from PyQt5.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtProperty, pyqtSignal, QTimer, QRectF, QPointF
from PyQt5.QtGui import (
    QPainter, QPixmap, QColor, QPainterPath, QFont, QPen,
    QLinearGradient, QRadialGradient, QBrush, QFontMetrics
)

from app.common.version import APP_NAME, __version__


class NeuroSplashScreen(QWidget):
    finished = pyqtSignal()

    def __init__(self, logo_path=None, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.SplashScreen
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        # High-end card proportions
        self.card_w = 440
        self.card_h = 450
        self.shadow_pad = 28
        self.setFixedSize(self.card_w + self.shadow_pad * 2, self.card_h + self.shadow_pad * 2)

        # Resolve logo path (prefer transparent PNG)
        self.logo_pixmap = None
        resolved_logo = self._resolve_logo_path(logo_path)
        if resolved_logo and os.path.exists(resolved_logo):
            raw = QPixmap(resolved_logo)
            if not raw.isNull():
                self.logo_pixmap = raw.scaled(86, 86, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        self._opacity = 1.0
        self._progress = 0.0
        self._is_closing = False

        # Multi-layer smooth shadow effect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(56)
        shadow.setColor(QColor(0, 0, 0, 185))
        shadow.setOffset(0, 12)
        self.setGraphicsEffect(shadow)

        # 60 FPS incremental progress timer (guarantees silky smooth motion on every device)
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)  # ~60 FPS
        self._anim_timer.timeout.connect(self._on_anim_step)

        # Opacity Fade-in Animation
        self.fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_anim.setDuration(240)
        self.fade_anim.setStartValue(0.0)
        self.fade_anim.setEndValue(1.0)
        self.fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Center on primary screen
        screen = QApplication.primaryScreen()
        if screen:
            geom = screen.availableGeometry()
            self.move((geom.width() - self.width()) // 2, (geom.height() - self.height()) // 2)

    def _resolve_logo_path(self, path):
        if path and os.path.exists(path):
            if "logo.jpg" in path:
                transparent_candidate = path.replace("logo.jpg", "logo_transparent.png")
                if os.path.exists(transparent_candidate):
                    return transparent_candidate
            return path

        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        p1 = os.path.join(base_dir, "assets", "logo_transparent.png")
        if os.path.exists(p1):
            return p1
        p2 = os.path.join(base_dir, "assets", "logo.jpg")
        if os.path.exists(p2):
            return p2
        return None

    def start(self):
        self.setWindowOpacity(0.0)
        self.show()
        self.fade_anim.start()
        # Start smooth timer ticking
        self._anim_timer.start()

    def _on_anim_step(self):
        # Guaranteed progressive fill across ~70 smooth frames
        if self._progress < 0.25:
            step = 0.014  # Smooth takeoff
        elif self._progress < 0.70:
            step = 0.020  # Fast linear glide through middle
        elif self._progress < 0.92:
            step = 0.014  # Smooth approach
        else:
            step = 0.008  # Gentle finish to exactly 100%

        self._progress = min(1.0, self._progress + step)
        self.update()

        if self._progress >= 1.0:
            self._anim_timer.stop()
            # Hold at 100% briefly so user sees completion, then finish
            QTimer.singleShot(220, self._start_finish)

    def _start_finish(self):
        if self._is_closing:
            return
        self._is_closing = True

        self.fade_out = QPropertyAnimation(self, b"windowOpacity")
        self.fade_out.setDuration(220)
        self.fade_out.setStartValue(1.0)
        self.fade_out.setEndValue(0.0)
        self.fade_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self.fade_out.finished.connect(self._complete_close)
        self.fade_out.start()

    def _complete_close(self):
        self.finished.emit()
        self.close()

    def get_opacity(self):
        return self._opacity

    def set_opacity(self, value):
        self._opacity = value
        self.setWindowOpacity(value)

    windowOpacity = pyqtProperty(float, get_opacity, set_opacity)

    def get_loading_progress(self):
        return self._progress

    def set_loading_progress(self, value):
        self._progress = max(0.0, min(1.0, value))
        self.update()

    loadingProgress = pyqtProperty(float, get_loading_progress, set_loading_progress)

    def _get_dynamic_status(self):
        if self._progress < 0.25:
            return "Initializing neural acceleration core..."
        elif self._progress < 0.55:
            return "Optimizing multi-segment download streams..."
        elif self._progress < 0.85:
            return "Loading smart rules & AI routing..."
        else:
            return "System ready • Launching workspace..."

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.TextAntialiasing)

        card_rect = QRectF(self.shadow_pad, self.shadow_pad, self.card_w, self.card_h)
        radius = 24.0

        # --- 1. Base Glass Card Path ---
        card_path = QPainterPath()
        card_path.addRoundedRect(card_rect, radius, radius)

        # Fill background with Deep Obsidian Mica gradient
        bg_gradient = QLinearGradient(card_rect.topLeft(), card_rect.bottomRight())
        bg_gradient.setColorAt(0.0, QColor(22, 24, 32, 248))
        bg_gradient.setColorAt(0.5, QColor(16, 18, 24, 252))
        bg_gradient.setColorAt(1.0, QColor(10, 12, 16, 255))
        painter.fillPath(card_path, bg_gradient)

        # Clip inner painting to rounded card
        painter.save()
        painter.setClipPath(card_path)

        # --- 2. Ambient Neural Glow Bloom (Dual Light Source) ---
        # Top-left Cyan Bloom
        cyan_center = QPointF(card_rect.left() + 100, card_rect.top() + 90)
        cyan_bloom = QRadialGradient(cyan_center, 175)
        cyan_bloom.setColorAt(0.0, QColor(0, 163, 255, 45))
        cyan_bloom.setColorAt(0.5, QColor(0, 163, 255, 16))
        cyan_bloom.setColorAt(1.0, QColor(0, 163, 255, 0))
        painter.fillRect(card_rect, QBrush(cyan_bloom))

        # Bottom-right Amber/Orange Bloom
        orange_center = QPointF(card_rect.right() - 100, card_rect.top() + 140)
        orange_bloom = QRadialGradient(orange_center, 160)
        orange_bloom.setColorAt(0.0, QColor(255, 110, 0, 38))
        orange_bloom.setColorAt(0.5, QColor(255, 110, 0, 12))
        orange_bloom.setColorAt(1.0, QColor(255, 110, 0, 0))
        painter.fillRect(card_rect, QBrush(orange_bloom))

        # --- 3. Floating App Logo Tile ---
        tile_size = 104.0
        tile_x = card_rect.left() + (self.card_w - tile_size) / 2.0
        tile_y = card_rect.top() + 48.0
        tile_rect = QRectF(tile_x, tile_y, tile_size, tile_size)
        tile_radius = 22.0

        # Ambient Glow behind Tile
        tile_glow = QRadialGradient(tile_rect.center(), 72)
        tile_glow.setColorAt(0.0, QColor(0, 180, 255, 65))
        tile_glow.setColorAt(0.6, QColor(255, 120, 0, 25))
        tile_glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(QRectF(tile_x - 30, tile_y - 30, tile_size + 60, tile_size + 60), QBrush(tile_glow))

        # Glass Tile Body
        tile_path = QPainterPath()
        tile_path.addRoundedRect(tile_rect, tile_radius, tile_radius)
        tile_grad = QLinearGradient(tile_rect.topLeft(), tile_rect.bottomRight())
        tile_grad.setColorAt(0.0, QColor(255, 255, 255, 20))
        tile_grad.setColorAt(1.0, QColor(255, 255, 255, 6))
        painter.fillPath(tile_path, tile_grad)

        # Glass Tile Rim Border
        tile_pen = QPen()
        tile_border_grad = QLinearGradient(tile_rect.topLeft(), tile_rect.bottomRight())
        tile_border_grad.setColorAt(0.0, QColor(255, 255, 255, 60))
        tile_border_grad.setColorAt(0.5, QColor(255, 255, 255, 20))
        tile_border_grad.setColorAt(1.0, QColor(255, 255, 255, 10))
        tile_pen.setBrush(QBrush(tile_border_grad))
        tile_pen.setWidthF(1.0)
        painter.strokePath(tile_path, tile_pen)

        # Draw Logo Pixmap
        if self.logo_pixmap and not self.logo_pixmap.isNull():
            lx = tile_rect.left() + (tile_size - self.logo_pixmap.width()) / 2.0
            ly = tile_rect.top() + (tile_size - self.logo_pixmap.height()) / 2.0
            painter.drawPixmap(int(lx), int(ly), self.logo_pixmap)

        # --- 4. Brand Title ---
        title_font = QFont("Segoe UI Variable Display", 22, QFont.Bold)
        title_font.setStyleStrategy(QFont.PreferAntialias)
        painter.setFont(title_font)
        painter.setPen(QColor(255, 255, 255))
        title_rect = QRectF(card_rect.left(), tile_y + tile_size + 18.0, self.card_w, 34.0)
        painter.drawText(title_rect, Qt.AlignCenter, "NeuroGet AI")

        # --- 5. Version Pill Badge ---
        badge_text = f"v{__version__}  •  Neural Acceleration"
        badge_font = QFont("Segoe UI", 9, QFont.DemiBold)
        badge_font.setStyleStrategy(QFont.PreferAntialias)
        painter.setFont(badge_font)
        fm = QFontMetrics(badge_font)
        text_w = fm.horizontalAdvance(badge_text)
        badge_w = text_w + 20.0
        badge_h = 22.0
        badge_x = card_rect.left() + (self.card_w - badge_w) / 2.0
        badge_y = title_rect.bottom() + 6.0
        badge_rect = QRectF(badge_x, badge_y, badge_w, badge_h)

        badge_path = QPainterPath()
        badge_path.addRoundedRect(badge_rect, 11.0, 11.0)
        painter.fillPath(badge_path, QColor(0, 163, 255, 20))

        b_pen = QPen(QColor(0, 180, 255, 70), 1.0)
        painter.strokePath(badge_path, b_pen)

        painter.setPen(QColor(60, 195, 255))
        painter.drawText(badge_rect, Qt.AlignCenter, badge_text)

        # --- 6. Dynamic Status Text & Percentage Row ---
        bar_w = 320.0
        bar_h = 5.0
        bar_x = card_rect.left() + (self.card_w - bar_w) / 2.0
        bar_y = card_rect.top() + 372.0

        status_font = QFont("Segoe UI", 9)
        status_font.setStyleStrategy(QFont.PreferAntialias)
        painter.setFont(status_font)

        # Left: Status description
        painter.setPen(QColor(155, 162, 180))
        status_rect = QRectF(bar_x, bar_y - 24.0, bar_w - 45.0, 18.0)
        painter.drawText(status_rect, Qt.AlignLeft | Qt.AlignVCenter, self._get_dynamic_status())

        # Right: Progress percentage
        pct_font = QFont("Segoe UI", 9, QFont.Bold)
        pct_font.setStyleStrategy(QFont.PreferAntialias)
        painter.setFont(pct_font)
        painter.setPen(QColor(60, 195, 255))
        pct_rect = QRectF(bar_x + bar_w - 45.0, bar_y - 24.0, 45.0, 18.0)
        painter.drawText(pct_rect, Qt.AlignRight | Qt.AlignVCenter, f"{int(self._progress * 100)}%")

        # --- 7. Glowing Fluid Progress Bar ---
        bar_track_rect = QRectF(bar_x, bar_y, bar_w, bar_h)

        # Track
        track_path = QPainterPath()
        track_path.addRoundedRect(bar_track_rect, 2.5, 2.5)
        painter.fillPath(track_path, QColor(255, 255, 255, 20))

        # Fill with Vibrant Solar-to-Cyan Gradient
        fill_w = max(0.0, min(bar_w, bar_w * self._progress))
        if fill_w > 0:
            fill_rect = QRectF(bar_x, bar_y, fill_w, bar_h)
            fill_path = QPainterPath()
            fill_path.addRoundedRect(fill_rect, 2.5, 2.5)

            bar_grad = QLinearGradient(bar_x, bar_y, bar_x + bar_w, bar_y)
            bar_grad.setColorAt(0.0, QColor(255, 120, 0))   # Warm Orange
            bar_grad.setColorAt(0.5, QColor(255, 180, 0))   # Gold
            bar_grad.setColorAt(1.0, QColor(0, 200, 255))   # Electric Cyan
            painter.fillPath(fill_path, bar_grad)

            # Glowing Laser Tip at head of progress
            tip_x = bar_x + fill_w
            tip_y = bar_y + bar_h / 2.0
            tip_glow = QRadialGradient(QPointF(tip_x, tip_y), 9.0)
            tip_glow.setColorAt(0.0, QColor(0, 225, 255, 230))
            tip_glow.setColorAt(0.4, QColor(0, 200, 255, 120))
            tip_glow.setColorAt(1.0, QColor(0, 200, 255, 0))
            painter.fillRect(QRectF(tip_x - 9, tip_y - 9, 18, 18), QBrush(tip_glow))

        painter.restore()

        # --- 8. Specular Outer Card Rim (Windows 11 Fluent Specular Edge) ---
        rim_pen = QPen()
        rim_grad = QLinearGradient(card_rect.topLeft(), card_rect.bottomRight())
        rim_grad.setColorAt(0.0, QColor(255, 255, 255, 52))
        rim_grad.setColorAt(0.3, QColor(255, 255, 255, 22))
        rim_grad.setColorAt(0.8, QColor(255, 255, 255, 8))
        rim_grad.setColorAt(1.0, QColor(255, 255, 255, 15))
        rim_pen.setBrush(QBrush(rim_grad))
        rim_pen.setWidthF(1.2)
        painter.strokePath(card_path, rim_pen)
