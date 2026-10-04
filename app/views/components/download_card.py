import os
import urllib.parse
import subprocess

from PyQt5.QtCore import Qt, QSize, QTimer, pyqtSignal, QThread, QPoint
from PyQt5.QtGui import QFontMetrics, QDesktopServices
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QVBoxLayout,
    QApplication,
    QSizePolicy
)

from qfluentwidgets import (
    ProgressBar,
    StrongBodyLabel,
    CaptionLabel,
    ToolButton,
    CardWidget,
    SimpleCardWidget,
    IconWidget,
    PushButton,
    PrimaryPushButton,
    MessageBox,
    LineEdit,
    InfoBar,
    RoundMenu,
    Action
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

    def __init__(self, archive_path, passwords, parent=None):
        super().__init__(parent)
        self.archive_path = archive_path
        self.passwords = passwords
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        result = PasswordFinder.extract_archive(
            self.archive_path,
            self.passwords,
            is_cancelled=lambda: self._is_cancelled
        )
        if not self._is_cancelled:
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
        self.category = category or "General"
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

        self.setMinimumHeight(114)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.hBoxLayout = QHBoxLayout(self)
        self.hBoxLayout.setContentsMargins(20, 16, 20, 16)
        self.hBoxLayout.setSpacing(16)

        self._update_icon()

        # Stylized Acrylic Icon Container
        self.iconCard = SimpleCardWidget(self)
        self.iconCard.setFixedSize(52, 52)
        icon_card_layout = QVBoxLayout(self.iconCard)
        icon_card_layout.setContentsMargins(0, 0, 0, 0)
        icon_card_layout.setAlignment(Qt.AlignCenter)

        self.iconWidget = IconWidget(self.icon_type, self.iconCard)
        self.iconWidget.setFixedSize(QSize(30, 30))
        icon_card_layout.addWidget(self.iconWidget, 0, Qt.AlignCenter)
        self.hBoxLayout.addWidget(self.iconCard)

        self.vBoxLayout = QVBoxLayout()
        self.vBoxLayout.setSpacing(8)

        # Header with Name, Category Tag, Threat Badge, and Speed
        self.headerLayout = QHBoxLayout()
        self.headerLayout.setSpacing(10)
        self.nameLabel = ElidedLabel(self.filename, self)
        
        self.categoryBadge = CaptionLabel(f"{self.category}", self)
        self._style_category_badge()

        self.threatBadge = CaptionLabel("", self)
        self.threatBadge.setStyleSheet("""
            CaptionLabel {
                color: #E81123;
                background-color: rgba(232, 17, 35, 0.15);
                border: 1px solid rgba(232, 17, 35, 0.3);
                border-radius: 5px;
                padding: 2px 8px;
                font-weight: 600;
                font-size: 11px;
            }
        """)
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
        self.btnSummary.setMinimumHeight(32)
        self.btnSummary.setToolTip("Generate instant semantic insights and chat with this file")
        self.btnSummary.clicked.connect(self.open_ai_summary)
        self.btnSummary.hide()

        # Archive Extra Action Buttons
        self.btnPassword = PushButton('Password', self, FIF.VPN)
        self.btnPassword.setMinimumHeight(32)
        self.btnPassword.setToolTip("View discovered extraction passwords")
        self.btnPassword.clicked.connect(self.show_smart_passwords)
        if not self.is_archive:
            self.btnPassword.hide()

        self.btnExtract = PushButton('Extract', self, FIF.ZIP_FOLDER)
        self.btnExtract.setMinimumHeight(32)
        self.btnExtract.setToolTip("Auto-extract archive to destination")
        self.btnExtract.clicked.connect(self.start_auto_extract)
        self.btnExtract.hide()

        self.btnOpenFolder = ToolButton(FIF.FOLDER, self)
        self.btnOpenFolder.setToolTip("Open Containing Folder")
        self.btnOpenFolder.clicked.connect(self.open_folder)
        self.btnOpenFolder.hide()

        self.btnPause = ToolButton(FIF.PAUSE, self)
        self.btnPause.setToolTip("Pause / Resume Download")
        self.btnPause.clicked.connect(self.toggle_pause)

        self.btnCancel = ToolButton(FIF.CLOSE, self)
        self.btnCancel.setToolTip("Cancel & Remove Task")
        self.btnCancel.clicked.connect(self.cancel_download)

        self.btnLayout.addWidget(self.btnSummary)
        self.btnLayout.addWidget(self.btnPassword)
        self.btnLayout.addWidget(self.btnExtract)
        self.btnLayout.addWidget(self.btnOpenFolder)
        self.btnLayout.addWidget(self.btnPause)
        self.btnLayout.addWidget(self.btnCancel)

        self.hBoxLayout.addLayout(self.btnLayout)

        # Context menu setup
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

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

    def _style_category_badge(self):
        cat = (self.category or "").lower()
        if "doc" in cat or "pdf" in cat or "book" in cat:
            color = "#0078D4"
            bg = "rgba(0, 120, 212, 0.12)"
            border = "rgba(0, 120, 212, 0.25)"
        elif "video" in cat or "media" in cat or "music" in cat or "audio" in cat:
            color = "#8764B8"
            bg = "rgba(135, 100, 184, 0.12)"
            border = "rgba(135, 100, 184, 0.25)"
        elif "archive" in cat or "zip" in cat or "compress" in cat:
            color = "#E36A00"
            bg = "rgba(227, 106, 0, 0.12)"
            border = "rgba(227, 106, 0, 0.25)"
        elif "app" in cat or "soft" in cat or "exe" in cat or "code" in cat:
            color = "#107C41"
            bg = "rgba(16, 124, 65, 0.12)"
            border = "rgba(16, 124, 65, 0.25)"
        else:
            color = "#008272"
            bg = "rgba(0, 130, 114, 0.12)"
            border = "rgba(0, 130, 114, 0.25)"

        self.categoryBadge.setStyleSheet(f"""
            CaptionLabel {{
                color: {color};
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 5px;
                padding: 2px 8px;
                font-weight: 600;
                font-size: 11px;
            }}
        """)

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
            self.save_dir,
            parent=self
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
        
        enable_renaming = get_setting("enable_ai_clean_renaming", "true").lower() in ("true", "1", "yes")
        if enable_renaming:
            self.filename = AIClient._heuristic_clean_name(real_filename)
        else:
            self.filename = real_filename

        self.nameLabel.setText(self.filename)
        self._update_icon()
        self.iconWidget.setIcon(self.icon_type)
        self._style_category_badge()

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
        pct_str = f" ({int((downloaded/self.total_size)*100)}%)" if self.total_size > 0 else ""
        self.sizeLabel.setText(f"{down_str} / {tot_str}{pct_str}")
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
            self.sizeLabel.setText(f"{size_str} / {size_str} (100%)")

        self.btnPause.hide()
        self.btnCancel.hide()
        self.btnSummary.show()
        self.btnOpenFolder.show()

        if self.is_archive:
            self.btnExtract.show()
            if get_setting("enable_auto_extract", "false").lower() in ("true", "1", "yes"):
                self.start_auto_extract(silent=True)

        self._emit_finished_once()

    def on_error(self, err_msg):
        self.state = "error"
        self.speedLabel.setText("Error")

        err_str = str(err_msg)
        short_err = "Download failed"
        err_lower = err_str.lower()
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
        self.extract_worker = ExtractWorker(filepath, passwords, parent=self)
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

    def open_file(self):
        filepath = self.completed_filepath or os.path.join(self.save_dir, self.filename)
        if os.path.exists(filepath):
            try:
                os.startfile(filepath)
            except Exception:
                subprocess.Popen(['explorer', filepath])

    def copy_url(self):
        if self.url:
            QApplication.clipboard().setText(self.url)
            InfoBar.success('Copied', 'Download link copied to clipboard.', parent=self.window(), duration=2500)

    def _show_context_menu(self, pos: QPoint):
        menu = RoundMenu(parent=self)

        if self.state == "completed":
            act_open = Action(FIF.DOCUMENT, "Open File", triggered=self.open_file)
            menu.addAction(act_open)

            act_summary = Action(FIF.ROBOT, "AI Document Summary", triggered=self.open_ai_summary)
            menu.addAction(act_summary)

            if self.is_archive:
                act_extract = Action(FIF.ZIP_FOLDER, "Extract Archive", triggered=self.start_auto_extract)
                menu.addAction(act_extract)

            act_folder = Action(FIF.FOLDER, "Open Containing Folder", triggered=self.open_folder)
            menu.addAction(act_folder)

        else:
            if self.state == "downloading":
                act_pause = Action(FIF.PAUSE, "Pause Download", triggered=self.toggle_pause)
                menu.addAction(act_pause)
            else:
                act_resume = Action(FIF.PLAY, "Resume Download", triggered=self.toggle_pause)
                menu.addAction(act_resume)

        menu.addSeparator()
        act_copy = Action(FIF.COPY, "Copy Download Link", triggered=self.copy_url)
        menu.addAction(act_copy)

        if self.is_archive:
            act_pwd = Action(FIF.VPN, "Find Extraction Passwords", triggered=self.show_smart_passwords)
            menu.addAction(act_pwd)

        menu.addSeparator()
        act_delete = Action(FIF.DELETE, "Cancel & Remove Task", triggered=self.cancel_download)
        menu.addAction(act_delete)

        menu.exec_(self.mapToGlobal(pos))

    def toggle_pause(self):
        if self.state == "downloading":
            self.state = "paused"
            self.worker.pause()
            self.speedLabel.setText("Paused")
            self.etaLabel.setText("")
            self.btnPause.setIcon(FIF.PLAY)
            self.db_timer.stop()
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
                self.db_timer.start(5000)

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
            worker = self.worker
            self.worker = None
            for sig in (worker.metadata_ready, worker.progress_update, worker.finished, worker.error):
                try:
                    sig.disconnect()
                except (TypeError, RuntimeError):
                    pass
            worker.cancel()
            try:
                worker.setParent(None)
                worker.finished.connect(worker.deleteLater)
            except (TypeError, RuntimeError):
                pass
            worker.wait(150)

        if hasattr(self, 'extract_worker') and self.extract_worker is not None:
            extract_worker = self.extract_worker
            self.extract_worker = None
            try:
                extract_worker.finished_extract.disconnect()
            except (TypeError, RuntimeError):
                pass
            extract_worker.cancel()
            try:
                extract_worker.setParent(None)
                extract_worker.finished.connect(extract_worker.deleteLater)
            except (TypeError, RuntimeError):
                pass
            extract_worker.wait(100)

        if self.task_id:
            update_task_progress(self.task_id, self.downloaded_size, self.total_size, status="error")

        self._emit_finished_once()
        self.deleteLater()