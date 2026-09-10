import os
import urllib.parse

from PyQt5.QtCore import Qt, QSize, QTimer, pyqtSignal
from PyQt5.QtGui import QFontMetrics
from PyQt5.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QFrame,
    QApplication,
    QSizePolicy
)

from qfluentwidgets import (
    ProgressBar,
    StrongBodyLabel,
    BodyLabel,
    CaptionLabel,
    ToolButton,
    CardWidget,
    IconWidget,
    PushButton,
    MessageBox,
    LineEdit,
    InfoBar
)

from qfluentwidgets import FluentIcon as FIF

from app.services.password_finder import PasswordFinder
from app.controllers.downloader import DownloadWorker
from app.models.database import update_task_progress


def format_size(bytes_size):
    if bytes_size <= 0:
        return "0 B"

    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0

    return f"{bytes_size:.1f} PB"


class ElidedLabel(StrongBodyLabel):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)

        self._full_text = text

        self.setMinimumWidth(0)
        self.setWordWrap(False)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setToolTip(text)

    def setText(self, text):
        self._full_text = text
        self.setToolTip(text)
        super().setText(text)
        self._elide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def showEvent(self, event):
        super().showEvent(event)
        self._elide()

    def _elide(self):
        if not hasattr(self, "_full_text"):
            return

        fm = QFontMetrics(self.font())
        available_width = max(0, self.width() - 4)

        elided_text = fm.elidedText(
            self._full_text,
            Qt.ElideRight,
            available_width
        )

        if super().text() != elided_text:
            super().setText(elided_text)


class DownloadCard(CardWidget):
    taskFinished = pyqtSignal(object)

    def __init__(
        self,
        url,
        raw_filename,
        save_dir,
        task_id=None,
        status="downloading",
        auto_start=True,
        parent=None
    ):
        super().__init__(parent)

        self.url = url
        self.filename = urllib.parse.unquote(raw_filename)
        self.save_dir = save_dir
        self.task_id = task_id

        self.state = status
        self.is_archive = False

        self.total_size = 0
        self.downloaded_size = 0

        self._finished_emitted = False
        self._started = False

        self.setFixedHeight(110)

        self.hBoxLayout = QHBoxLayout(self)
        self.hBoxLayout.setContentsMargins(20, 16, 20, 16)
        self.hBoxLayout.setSpacing(16)

        ext = self.filename.lower().split('.')[-1] if '.' in self.filename else ''

        if ext in ['zip', 'rar', '7z', 'tar', 'gz']:
            icon_type = FIF.ZIP_FOLDER
            self.is_archive = True
        elif ext in ['mp3', 'wav', 'aac', 'flac', 'ogg']:
            icon_type = FIF.MUSIC
        elif ext in ['mp4', 'mkv', 'avi', 'mov', 'wmv']:
            icon_type = FIF.VIDEO
        elif ext in ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg']:
            icon_type = FIF.PHOTO
        elif ext in ['exe', 'msi', 'apk', 'dmg', 'iso']:
            icon_type = FIF.APPLICATION
        else:
            icon_type = FIF.DOCUMENT

        self.iconWidget = IconWidget(icon_type, self)
        self.iconWidget.setFixedSize(QSize(40, 40))

        self.hBoxLayout.addWidget(self.iconWidget)

        self.vBoxLayout = QVBoxLayout()
        self.vBoxLayout.setSpacing(8)

        self.headerLayout = QHBoxLayout()

        self.nameLabel = ElidedLabel(self.filename, self)
        self.speedLabel = CaptionLabel("Connecting...", self)

        self.headerLayout.addWidget(self.nameLabel)
        self.headerLayout.addStretch()
        self.headerLayout.addWidget(self.speedLabel)

        self.progressBar = ProgressBar(self)
        self.progressBar.setValue(0)

        self.footerLayout = QHBoxLayout()

        self.sizeLabel = CaptionLabel("Resolving size...", self)
        self.etaLabel = CaptionLabel("ETA: --:--", self)

        self.footerLayout.addWidget(self.sizeLabel)
        self.footerLayout.addStretch()
        self.footerLayout.addWidget(self.etaLabel)

        self.vBoxLayout.addLayout(self.headerLayout)
        self.vBoxLayout.addWidget(self.progressBar)
        self.vBoxLayout.addLayout(self.footerLayout)

        self.hBoxLayout.addLayout(self.vBoxLayout)

        self.btnLayout = QHBoxLayout()
        self.btnLayout.setSpacing(8)

        if self.is_archive:
            self.btnPassword = PushButton('🔑 Password', self)
            self.btnPassword.clicked.connect(self.show_smart_passwords)
            self.btnLayout.addWidget(self.btnPassword)

        self.btnPause = ToolButton(FIF.PAUSE, self)
        self.btnPause.clicked.connect(self.toggle_pause)

        self.btnCancel = ToolButton(FIF.CLOSE, self)
        self.btnCancel.clicked.connect(self.cancel_download)

        self.btnLayout.addWidget(self.btnPause)
        self.btnLayout.addWidget(self.btnCancel)

        self.hBoxLayout.addLayout(self.btnLayout)

        self.worker = None

        self.db_timer = QTimer(self)
        self.db_timer.timeout.connect(self.sync_db)

        self._create_worker()

        if self.state == "completed":
            self.progressBar.setValue(100)
            self.speedLabel.setText("Completed")
            self.btnPause.hide()
            self.btnCancel.hide()

        elif self.state == "error":
            self.speedLabel.setText("Error / Cancelled")
            self.btnPause.setIcon(FIF.SYNC)

        elif self.state == "paused":
            self.speedLabel.setText("Paused")
            self.btnPause.setIcon(FIF.PLAY)

        elif auto_start:
            self.start_download()

        else:
            self.state = "queued"
            self.speedLabel.setText("Queued")
            self.btnPause.setEnabled(False)

    def _create_worker(self):
        self.worker = DownloadWorker(
            self.task_id,
            self.url,
            self.save_dir
        )

        self.worker.metadata_ready.connect(self.on_metadata_ready)
        self.worker.progress_update.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)

    def start_download(self):
        if self._started:
            return

        if self.state == "completed":
            return

        self._started = True

        if self.state in ("queued", "pending", "paused"):
            self.state = "downloading"
            self.btnPause.setEnabled(True)
            self.btnPause.setIcon(FIF.PAUSE)

        self.speedLabel.setText("Connecting...")
        self.etaLabel.setText("ETA: --:--")

        if self.worker is None:
            self._create_worker()

        if not self.worker.isRunning():
            self.worker.start()

        self.db_timer.start(5000)

    def _emit_finished_once(self):
        if not self._finished_emitted:
            self._finished_emitted = True
            self.taskFinished.emit(self)

    def sync_db(self):
        if self.state == "downloading" and self.task_id:
            update_task_progress(
                self.task_id,
                self.downloaded_size,
                self.total_size,
                status="downloading"
            )

    def on_metadata_ready(self, real_filename, total_size):
        self.filename = real_filename
        self.total_size = total_size

        self.nameLabel.setText(self.filename)

        size_str = format_size(self.total_size)
        self.sizeLabel.setText(f"0 B / {size_str}")

    def on_progress(self, downloaded, speed, eta):
        self.downloaded_size = downloaded

        if self.total_size > 0:
            pct = int((downloaded / self.total_size) * 100)
            self.progressBar.setValue(pct)

        down_str = format_size(downloaded)
        tot_str = format_size(self.total_size) if self.total_size > 0 else "Unknown"

        self.sizeLabel.setText(f"{down_str} / {tot_str}")
        self.speedLabel.setText(f"{format_size(speed)}/s")
        self.etaLabel.setText(f"{eta} left")

    def on_finished(self, filepath):
        self.state = "completed"
        self.speedLabel.setText("Completed")
        self.etaLabel.setText("")
        self.progressBar.setValue(100)

        self.db_timer.stop()

        if self.task_id:
            update_task_progress(
                self.task_id,
                self.total_size,
                self.total_size,
                status="completed"
            )

        if self.total_size > 0:
            size_str = format_size(self.total_size)
            self.sizeLabel.setText(f"{size_str} / {size_str}")

        self.btnPause.hide()
        self.btnCancel.hide()

        self._emit_finished_once()

    def on_error(self, err_msg):
        self.state = "error"
        self.speedLabel.setText("Error")
        self.etaLabel.setText(str(err_msg))
        self.btnPause.setIcon(FIF.SYNC)

        self.db_timer.stop()

        if self.task_id:
            update_task_progress(
                self.task_id,
                self.downloaded_size,
                self.total_size,
                status="error"
            )

        if "cancelled" not in str(err_msg).lower():
            InfoBar.error(
                "Download Failed",
                f"Failed to download {self.filename}: {err_msg}",
                parent=self.window()
            )

        self._emit_finished_once()

    def show_smart_passwords(self):
        passwords = PasswordFinder.get_probable_passwords(self.url, self.filename)

        if not passwords:
            passwords = ["Could not determine password from URL."]

        w = MessageBox(
            'Smart Password Finder',
            'Probable extraction passwords based on the download source:',
            self.window()
        )

        for pwd in passwords:
            line_edit = LineEdit(w.widget)
            line_edit.setText(pwd)
            line_edit.setReadOnly(True)
            w.textLayout.addWidget(line_edit)

        w.yesButton.setText('Copy First & Close')
        w.cancelButton.setText('Close')

        if w.exec():
            if passwords:
                QApplication.clipboard().setText(passwords[0])
                InfoBar.success(
                    'Copied',
                    f'Copied password to clipboard:\n{passwords[0]}',
                    parent=self.window()
                )

    def toggle_pause(self):
        if self.state == "downloading":
            self.state = "paused"
            self.worker.pause()

            self.speedLabel.setText("Paused")
            self.etaLabel.setText("")
            self.btnPause.setIcon(FIF.PLAY)

            if self.task_id:
                update_task_progress(
                    self.task_id,
                    self.downloaded_size,
                    self.total_size,
                    status="paused"
                )

        elif self.state == "paused":
            if not self._started:
                self.start_download()
            else:
                self.state = "downloading"
                self.worker.resume()

                self.speedLabel.setText("Connecting...")
                self.btnPause.setIcon(FIF.PAUSE)

            if self.task_id:
                update_task_progress(
                    self.task_id,
                    self.downloaded_size,
                    self.total_size,
                    status="downloading"
                )

        elif self.state == "error":
            self.state = "downloading"

            self.btnPause.setIcon(FIF.PAUSE)
            self.speedLabel.setText("Connecting...")
            self.etaLabel.setText("ETA: --:--")

            self._create_worker()
            self.worker.start()
            self.db_timer.start(5000)

            if self.task_id:
                update_task_progress(
                    self.task_id,
                    self.downloaded_size,
                    self.total_size,
                    status="downloading"
                )

    def cancel_download(self):
        self.db_timer.stop()

        if self.worker is not None:
            self.worker.cancel()
            self.worker.wait(2000)

        if self.task_id:
            update_task_progress(
                self.task_id,
                self.downloaded_size,
                self.total_size,
                status="error"
            )

        self._emit_finished_once()
        self.deleteLater()