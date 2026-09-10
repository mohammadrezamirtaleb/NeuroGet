import os
import urllib.parse
import subprocess

from PyQt5.QtCore import Qt, QSize, QTimer, pyqtSignal, QThread
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
    PrimaryPushButton,
    MessageBox,
    LineEdit,
    InfoBar,
    InfoBarPosition
)

from qfluentwidgets import FluentIcon as FIF

from app.services.password_finder import PasswordFinder
from app.services.ai_client import AIClient
from app.services.threat_detector import ThreatDetector
from app.controllers.downloader import DownloadWorker
from app.models.database import update_task_progress, update_task_metadata, get_setting
from app.views.components.ai_summary_dialog import AISummaryDialog


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
        super().__init__(parent=parent)
        self._full_text = text
        self.setMinimumWidth(0)
        self.setWordWrap(False)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setText(text)

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
        elided_text = fm.elidedText(self._full_text, Qt.ElideRight, available_width)
        if super().text() != elided_text:
            super().setText(elided_text)


class ExtractWorker(QThread):
    finished_extract = pyqtSignal(dict)

    def __init__(self, archive_path, passwords):
        super().__init__()
        self.archive_path = archive_path
        self.passwords = passwords

    def run(self):
        result = PasswordFinder.extract_archive(self.archive_path, self.passwords)
        self.finished_extract.emit(result)


class DownloadCard(CardWidget):
    taskFinished = pyqtSignal(object)

    def __init__(
        self,
        url,
        raw_filename,
        save_dir,
        task_id=None,
        status="downloading",
        category="General",
        threat_level="safe",
        auto_start=True,
        parent=None
    ):
        super().__init__(parent)

        self.url = url
        self.raw_filename = raw_filename
        self.filename = urllib.parse.unquote(raw_filename)
        self.save_dir = save_dir
        self.task_id = task_id
        self.category = category
        self.threat_level = threat_level

        self.state = status
        self.is_archive = False
        self.completed_filepath = ""

        self.total_size = 0
        self.downloaded_size = 0

        self._finished_emitted = False
        self._started = False

        # Try clean renaming if enabled
        enable_renaming = get_setting("enable_ai_clean_renaming", "true").lower() in ("true", "1", "yes")
        if enable_renaming:
            self.filename = AIClient._heuristic_clean_name(self.filename)

        self.setFixedHeight(115)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.hBoxLayout = QHBoxLayout(self)
        self.hBoxLayout.setContentsMargins(20, 16, 20, 16)
        self.hBoxLayout.setSpacing(16)

        self._update_icon()

        self.iconWidget = IconWidget(self.icon_type, self)
        self.iconWidget.setFixedSize(QSize(40, 40))
        self.hBoxLayout.addWidget(self.iconWidget)

        self.vBoxLayout = QVBoxLayout()
        self.vBoxLayout.setSpacing(8)

        # Header with Name, Category Tag, Threat Badge, and Status
        self.headerLayout = QHBoxLayout()
        self.nameLabel = ElidedLabel(self.filename, self)
        
        self.categoryBadge = CaptionLabel(f"[{self.category}]", self)
        self.categoryBadge.setStyleSheet("color: #0078D4; font-weight: bold;")

        self.threatBadge = CaptionLabel("", self)
        self.threatBadge.setStyleSheet("color: #E81123; font-weight: bold;")
        self.threatBadge.hide()

        self.speedLabel = CaptionLabel("Connecting...", self)

        self.headerLayout.addWidget(self.nameLabel, 1)
        self.headerLayout.addWidget(self.categoryBadge)
        self.headerLayout.addWidget(self.threatBadge)
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

        self.hBoxLayout.addLayout(self.vBoxLayout, 1)

        # Action Buttons
        self.btnLayout = QHBoxLayout()
        self.btnLayout.setSpacing(8)

        # AI Summary Button (Shown when completed)
        self.btnSummary = PushButton('AI Summary', self, FIF.ROBOT)
        self.btnSummary.clicked.connect(self.open_ai_summary)
        self.btnSummary.hide()

        # Archive Extra Action Buttons
        self.btnPassword = PushButton('Password', self, FIF.VPN)
        self.btnPassword.clicked.connect(self.show_smart_passwords)
        if not self.is_archive:
            self.btnPassword.hide()

        self.btnExtract = PushButton('Extract', self, FIF.ZIP_FOLDER)
        self.btnExtract.clicked.connect(self.start_auto_extract)
        self.btnExtract.hide()

        self.btnOpenFolder = ToolButton(FIF.FOLDER, self)
        self.btnOpenFolder.setToolTip("Open in Folder")
        self.btnOpenFolder.clicked.connect(self.open_folder)
        self.btnOpenFolder.hide()

        self.btnPause = ToolButton(FIF.PAUSE, self)
        self.btnPause.clicked.connect(self.toggle_pause)

        self.btnCancel = ToolButton(FIF.CLOSE, self)
        self.btnCancel.clicked.connect(self.cancel_download)

        self.btnLayout.addWidget(self.btnSummary)
        self.btnLayout.addWidget(self.btnPassword)
        self.btnLayout.addWidget(self.btnExtract)
        self.btnLayout.addWidget(self.btnOpenFolder)
        self.btnLayout.addWidget(self.btnPause)
        self.btnLayout.addWidget(self.btnCancel)

        self.hBoxLayout.addLayout(self.btnLayout)

        self.worker = None
        self.db_timer = QTimer(self)
        self.db_timer.timeout.connect(self.sync_db)

        self._create_worker()

        # Check initial threats
        self._check_threats(self.filename, 0)

        if self.state == "completed":
            self.progressBar.setValue(100)
            self.speedLabel.setText("Completed")
            self.btnPause.hide()
            self.btnCancel.hide()
            self.btnSummary.show()
            self.btnOpenFolder.show()
            if self.is_archive:
                self.btnExtract.show()

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

    def _update_icon(self):
        ext = self.filename.lower().split('.')[-1] if '.' in self.filename else ''
        if ext in ['zip', 'rar', '7z', 'tar', 'gz', 'bz2']:
            self.icon_type = FIF.ZIP_FOLDER
            self.is_archive = True
        elif ext in ['mp3', 'wav', 'aac', 'flac', 'ogg', 'm4a']:
            self.icon_type = FIF.MUSIC
            self.is_archive = False
        elif ext in ['mp4', 'mkv', 'avi', 'mov', 'wmv', 'flv', 'webm']:
            self.icon_type = FIF.VIDEO
            self.is_archive = False
        elif ext in ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'ico']:
            self.icon_type = FIF.PHOTO
            self.is_archive = False
        elif ext in ['exe', 'msi', 'apk', 'dmg', 'iso', 'deb', 'rpm']:
            self.icon_type = FIF.APPLICATION
            self.is_archive = False
        else:
            self.icon_type = FIF.DOCUMENT
            self.is_archive = False

    def _check_threats(self, filename, total_size):
        enable_threat = get_setting("enable_threat_detection", "true").lower() in ("true", "1", "yes")
        if not enable_threat:
            return

        threat = ThreatDetector.analyze_download(filename, self.url, total_size)
        if not threat["is_safe"]:
            self.threat_level = threat["level"]
            self.threatBadge.setText("Suspicious" if threat["level"] == "warning" else "High Risk")
            self.threatBadge.setToolTip("\n".join(threat["reasons"]))
            self.threatBadge.show()
            if self.task_id:
                update_task_metadata(self.task_id, threat_level=self.threat_level)

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
        if self._started or self.state == "completed":
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
        self.total_size = total_size
        
        # Clean rename via AI / Heuristic
        enable_renaming = get_setting("enable_ai_clean_renaming", "true").lower() in ("true", "1", "yes")
        if enable_renaming:
            self.filename = AIClient.clean_filename(real_filename, self.url)
        else:
            self.filename = real_filename

        self.nameLabel.setText(self.filename)
        self._update_icon()
        self.iconWidget.setIcon(self.icon_type)

        if self.is_archive:
            self.btnPassword.show()

        size_str = format_size(self.total_size)
        self.sizeLabel.setText(f"0 B / {size_str}")

        # Re-check threat profile with real filename and size
        self._check_threats(self.filename, self.total_size)

        if self.task_id:
            update_task_metadata(self.task_id, filename=self.filename)

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
        self.completed_filepath = filepath
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
        self.btnSummary.show()
        self.btnOpenFolder.show()

        if self.is_archive:
            self.btnExtract.show()
            # Auto extract if user enabled it in settings
            if get_setting("enable_auto_extract", "false").lower() in ("true", "1", "yes"):
                self.start_auto_extract(silent=True)

        self._emit_finished_once()

    def on_error(self, err_msg):
        self.state = "error"
        self.speedLabel.setText("Error")

        err_str = str(err_msg)
        short_err = "Download failed"
        err_lower = err_lower = err_str.lower()
        if "timeout" in err_lower or "timed out" in err_lower:
            short_err = "Connection timed out"
        elif "resolve" in err_lower or "dns" in err_lower or "getaddrinfo" in err_lower:
            short_err = "Host not found"
        elif "refused" in err_lower:
            short_err = "Connection refused"
        elif "404" in err_str:
            short_err = "File not found (404)"
        elif "403" in err_str:
            short_err = "Access denied (403)"
        elif "cancelled" in err_lower:
            short_err = "Cancelled"

        self.etaLabel.setText(short_err)
        self.etaLabel.setToolTip(err_str)
        self.btnPause.setIcon(FIF.SYNC)
        self.db_timer.stop()

        if self.task_id:
            update_task_progress(
                self.task_id,
                self.downloaded_size,
                self.total_size,
                status="error"
            )

        if "cancelled" not in err_lower:
            InfoBar.error(
                "Download Failed",
                f"Failed to download {self.filename}: {short_err}",
                parent=self.window()
            )

        self._emit_finished_once()

    def open_ai_summary(self):
        filepath = self.completed_filepath or os.path.join(self.save_dir, self.filename)
        if not os.path.exists(filepath):
            InfoBar.warning("File Missing", "Downloaded file cannot be found at the target path.", parent=self.window())
            return

        dialog = AISummaryDialog(filepath, parent=self.window())
        dialog.exec_()

    def start_auto_extract(self, silent=False):
        filepath = self.completed_filepath or os.path.join(self.save_dir, self.filename)
        if not os.path.exists(filepath):
            return

        self.btnExtract.setEnabled(False)
        self.btnExtract.setText("Extracting...")

        passwords = PasswordFinder.get_probable_passwords(self.url, self.filename)
        self.extract_worker = ExtractWorker(filepath, passwords)
        self.extract_worker.finished_extract.connect(lambda res: self._on_extract_finished(res, silent))
        self.extract_worker.start()

    def _on_extract_finished(self, result, silent):
        self.btnExtract.setEnabled(True)
        self.btnExtract.setText("Extract")

        if result.get("success"):
            if not silent:
                InfoBar.success(
                    "Extraction Complete",
                    f"{result.get('message')} (Password: {result.get('password_used')})",
                    parent=self.window(),
                    duration=4000
                )
        else:
            if not silent:
                InfoBar.warning(
                    "Extraction Failed",
                    result.get("message", "Could not unpack archive."),
                    parent=self.window(),
                    duration=4000
                )

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

    def open_folder(self):
        folder = self.save_dir
        if os.path.exists(folder):
            try:
                os.startfile(folder)
            except Exception:
                subprocess.Popen(['explorer', folder])

    def toggle_pause(self):
        if self.state == "downloading":
            self.state = "paused"
            self.worker.pause()
            self.speedLabel.setText("Paused")
            self.etaLabel.setText("")
            self.btnPause.setIcon(FIF.PLAY)
            if self.task_id:
                update_task_progress(self.task_id, self.downloaded_size, self.total_size, status="paused")

        elif self.state == "paused":
            if not self._started:
                self.start_download()
            else:
                self.state = "downloading"
                self.worker.resume()
                self.speedLabel.setText("Connecting...")
                self.btnPause.setIcon(FIF.PAUSE)

            if self.task_id:
                update_task_progress(self.task_id, self.downloaded_size, self.total_size, status="downloading")

        elif self.state == "error":
            self.state = "downloading"
            self.btnPause.setIcon(FIF.PAUSE)
            self.speedLabel.setText("Connecting...")
            self.etaLabel.setText("ETA: --:--")

            self._create_worker()
            self.worker.start()
            self.db_timer.start(5000)

            if self.task_id:
                update_task_progress(self.task_id, self.downloaded_size, self.total_size, status="downloading")

    def cancel_download(self):
        self.db_timer.stop()
        if self.worker is not None:
            self.worker.cancel()
            self.worker.wait(2000)

        if self.task_id:
            update_task_progress(self.task_id, self.downloaded_size, self.total_size, status="error")

        self._emit_finished_once()
        self.deleteLater()