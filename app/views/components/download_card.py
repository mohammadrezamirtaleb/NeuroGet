import os
import urllib.parse
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QFrame, QApplication
from PyQt5.QtCore import Qt, QSize, QTimer
from qfluentwidgets import (ProgressBar, StrongBodyLabel, BodyLabel, 
                            CaptionLabel, ToolButton, CardWidget, IconWidget,
                            PushButton, MessageBox, LineEdit, InfoBar)
from qfluentwidgets import FluentIcon as FIF

from app.services.password_finder import PasswordFinder
from app.controllers.downloader import DownloadWorker
from app.models.database import update_task_progress

def format_size(bytes_size):
    if bytes_size <= 0: return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} PB"

class DownloadCard(CardWidget):
    def __init__(self, url, raw_filename, save_dir, task_id=None, status="downloading", parent=None):
        super().__init__(parent)
        self.url = url
        self.filename = urllib.parse.unquote(raw_filename)
        self.save_dir = save_dir
        self.task_id = task_id
        
        self.state = status
        self.is_archive = False
        self.total_size = 0
        self.downloaded_size = 0
        
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
        self.nameLabel = StrongBodyLabel(self.filename, self)
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
        
        self.worker = DownloadWorker(self.task_id, self.url, self.save_dir)
        self.worker.metadata_ready.connect(self.on_metadata_ready)
        self.worker.progress_update.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        
        self.db_timer = QTimer(self)
        self.db_timer.timeout.connect(self.sync_db)
        
        if self.state != "completed" and self.state != "error":
            self.worker.start()
            self.db_timer.start(5000)
        elif self.state == "completed":
            self.progressBar.setValue(100)
            self.speedLabel.setText("Completed")
            self.btnPause.hide()
            self.btnCancel.hide()
        elif self.state == "error":
            self.speedLabel.setText("Error / Cancelled")
            self.btnPause.setIcon(FIF.PLAY)
            self.state = "paused" # Treat error as paused so they can retry

    def sync_db(self):
        if self.state == "downloading" and self.task_id:
            update_task_progress(self.task_id, self.downloaded_size, self.total_size, status="downloading")

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
            update_task_progress(self.task_id, self.total_size, self.total_size, status="completed")
        
        if self.total_size > 0:
            size_str = format_size(self.total_size)
            self.sizeLabel.setText(f"{size_str} / {size_str}")
            
        self.btnPause.hide()

    def on_error(self, err_msg):
        self.state = "error"
        self.speedLabel.setText("Error")
        self.etaLabel.setText(str(err_msg))
        self.btnPause.setIcon(FIF.SYNC)
        self.db_timer.stop()
        
        if self.task_id:
            update_task_progress(self.task_id, self.downloaded_size, self.total_size, status="error")
            
        InfoBar.error("Download Failed", f"Failed to download {self.filename}: {err_msg}", parent=self.window())

    def show_smart_passwords(self):
        passwords = PasswordFinder.get_probable_passwords(self.url, self.filename)
        if not passwords:
            passwords = ["Could not determine password from URL."]
            
        w = MessageBox('Smart Password Finder', 'Probable extraction passwords based on the download source:', self.window())
        
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
                InfoBar.success('Copied', f'Copied password to clipboard:\n{passwords[0]}', parent=self.window())
            
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
            self.state = "downloading"
            self.worker.resume()
            self.btnPause.setIcon(FIF.PAUSE)
            if self.task_id:
                update_task_progress(self.task_id, self.downloaded_size, self.total_size, status="downloading")
        elif self.state == "error":
            self.state = "downloading"
            self.btnPause.setIcon(FIF.PAUSE)
            self.speedLabel.setText("Connecting...")
            self.etaLabel.setText("ETA: --:--")
            
            # Recreate and restart worker for retry
            self.worker = DownloadWorker(self.task_id, self.url, self.save_dir)
            self.worker.downloaded_size = self.downloaded_size
            self.worker.total_size = self.total_size
            self.worker.metadata_ready.connect(self.on_metadata_ready)
            self.worker.progress_update.connect(self.on_progress)
            self.worker.finished.connect(self.on_finished)
            self.worker.error.connect(self.on_error)
            self.worker.start()
            
            self.db_timer.start(5000)
            if self.task_id:
                update_task_progress(self.task_id, self.downloaded_size, self.total_size, status="downloading")

    def cancel_download(self):
        self.db_timer.stop()
        self.worker.cancel()
        self.worker.wait(2000) # Wait for thread to finish safely
        if self.task_id:
            update_task_progress(self.task_id, self.downloaded_size, self.total_size, status="error")
        self.deleteLater()
