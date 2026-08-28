from PyQt5.QtWidgets import QWidget, QApplication, QGraphicsDropShadowEffect
from PyQt5.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtProperty, pyqtSignal, QTimer, QRectF
from PyQt5.QtGui import QPainter, QPixmap, QColor, QPainterPath, QFont, QPen, QLinearGradient

class NeuroSplashScreen(QWidget):
    finished = pyqtSignal()

    def __init__(self, logo_path, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.SplashScreen)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        self.setFixedSize(480, 520)
        
        # Load the logo (which is a dark square)
        self.logo = QPixmap(logo_path)
        # Scale logo down slightly for elegance
        self.logo = self.logo.scaled(180, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        self._opacity = 0.0
        self._progress = 0.0

        # Opacity Fade-in Animation
        self.fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_anim.setDuration(800)
        self.fade_anim.setStartValue(0.0)
        self.fade_anim.setEndValue(1.0)
        self.fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Loading Progress Animation
        self.prog_anim = QPropertyAnimation(self, b"loadingProgress")
        self.prog_anim.setDuration(2500)
        self.prog_anim.setStartValue(0.0)
        self.prog_anim.setEndValue(1.0)
        self.prog_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.prog_anim.finished.connect(self._on_done)
        
        # Shadow effect for that rich Fluent / modern feel
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(60)
        shadow.setColor(QColor(0, 0, 0, 150))
        shadow.setOffset(0, 15)
        self.setGraphicsEffect(shadow)
        
        # Center on screen
        desktop = QApplication.primaryScreen().geometry()
        self.move((desktop.width() - self.width()) // 2, (desktop.height() - self.height()) // 2)

    def start(self):
        self.show()
        self.fade_anim.start()
        self.prog_anim.start()

    def _on_done(self):
        # Hold the 100% full bar state for a brief moment before fading out
        self.set_loading_progress(1.0)
        QTimer.singleShot(400, self._start_fade_out)

    def _start_fade_out(self):
        self.fade_out = QPropertyAnimation(self, b"windowOpacity")
        self.fade_out.setDuration(500)
        self.fade_out.setStartValue(1.0)
        self.fade_out.setEndValue(0.0)
        self.fade_out.finished.connect(self._finish_and_close)
        self.fade_out.start()

    def _finish_and_close(self):
        self.finished.emit()
        self.close()

    # Property for opacity
    def get_opacity(self):
        return self._opacity
        
    def set_opacity(self, value):
        self._opacity = value
        self.setWindowOpacity(value)

    windowOpacity = pyqtProperty(float, get_opacity, set_opacity)

    # Property for loading progress
    def get_loading_progress(self):
        return self._progress
        
    def set_loading_progress(self, value):
        self._progress = value
        self.update()

    loadingProgress = pyqtProperty(float, get_loading_progress, set_loading_progress)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Background: Rich Dark Rounded Rectangle
        rect = QRectF(20, 20, self.width() - 40, self.height() - 40)
        path = QPainterPath()
        path.addRoundedRect(rect, 24, 24)
        
        # Gradient background
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QColor(25, 25, 30))
        gradient.setColorAt(1.0, QColor(10, 10, 15))
        painter.fillPath(path, gradient)
        
        # Draw Logo
        logo_x = int((self.width() - self.logo.width()) / 2)
        logo_y = 80
        painter.drawPixmap(logo_x, logo_y, self.logo)
        
        # Draw App Name
        painter.setPen(QColor(255, 255, 255))
        font = QFont("Segoe UI Variable Display", 28, QFont.Bold)
        painter.setFont(font)
        painter.drawText(QRectF(0, logo_y + self.logo.height() + 30, self.width(), 50), Qt.AlignCenter, "NeuroGet AI")
        
        # Draw Subtitle
        painter.setPen(QColor(150, 150, 160))
        sub_font = QFont("Segoe UI", 11)
        painter.setFont(sub_font)
        painter.drawText(QRectF(0, logo_y + self.logo.height() + 85, self.width(), 30), Qt.AlignCenter, "Initializing smart routing engine...")

        # Draw Loading Bar Track
        bar_width = 300
        bar_height = 4
        bar_x = (self.width() - bar_width) / 2
        bar_y = self.height() - 70
        
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(50, 50, 60))
        painter.drawRoundedRect(int(bar_x), int(bar_y), bar_width, bar_height, 2, 2)
        
        # Draw Loading Bar Fill (Orange/Blue glowing effect based on progress)
        fill_width = int(bar_width * self._progress)
        if fill_width > 0:
            fill_gradient = QLinearGradient(bar_x, bar_y, bar_x + bar_width, bar_y)
            fill_gradient.setColorAt(0.0, QColor(255, 120, 0)) # Orange
            fill_gradient.setColorAt(1.0, QColor(0, 170, 255)) # Blue
            
            painter.setBrush(fill_gradient)
            painter.drawRoundedRect(int(bar_x), int(bar_y), fill_width, bar_height, 2, 2)
