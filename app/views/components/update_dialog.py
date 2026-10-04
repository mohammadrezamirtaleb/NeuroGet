import os
import webbrowser
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget, QTextEdit, QSizePolicy, QApplication
)
from PyQt5.QtCore import Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from qfluentwidgets import (
    TitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton, CardWidget, SimpleCardWidget, IconWidget,
    ProgressBar, InfoBar, InfoBarPosition, TextEdit
)
from qfluentwidgets import FluentIcon as FIF

from app.common.version import APP_NAME, __version__
from app.services.updater import UpdateDownloadWorker
from app.services.update_installer import UpdateInstaller


def format_size(bytes_size):
    if bytes_size <= 0:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} PB"


class UpdateDialog(QDialog):
    """Interactive Windows 11 Fluent Design update dialog with direct in-app downloading,
    live progress tracking, SHA-256 integrity verification, and one-click install & restart.
    """

    def __init__(self, update_info: dict, parent=None):
        super().__init__(parent)
        self.update_info = update_info
        self.download_worker = None
        self.downloaded_installer_path = ""

        self.setWindowTitle(f"{APP_NAME} - Software Update Available")
        self.setMinimumSize(540, 440)
        self.resize(620, 520)

        from qfluentwidgets import isDarkTheme
        bg_color = "rgb(32, 32, 32)" if isDarkTheme() else "rgb(243, 243, 243)"
        self.setStyleSheet(f"UpdateDialog {{ background-color: {bg_color}; }}")

        self._init_ui()

    def _init_ui(self):
        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(24, 18, 24, 18)
        self.vbox.setSpacing(14)

        # 1. Header Card
        header_card = CardWidget(self)
        h_layout = QHBoxLayout(header_card)
        h_layout.setContentsMargins(16, 14, 16, 14)
        h_layout.setSpacing(14)

        icon_widget = IconWidget(FIF.SYNC, header_card)
        icon_widget.setFixedSize(36, 36)
        h_layout.addWidget(icon_widget)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)

        latest_ver = self.update_info.get("latest_version", "New")
        current_ver = self.update_info.get("current_version", __version__)
        channel = self.update_info.get("channel", "stable").capitalize()

        main_title = TitleLabel(f"New {APP_NAME} Update Available!", header_card)
        main_title.setWordWrap(True)
        version_sub = CaptionLabel(
            f"Current version: v{current_ver}   →   New version: v{latest_ver} ({channel})",
            header_card
        )
        version_sub.setWordWrap(True)

        title_col.addWidget(main_title)
        title_col.addWidget(version_sub)
        h_layout.addLayout(title_col, 1)

        self.vbox.addWidget(header_card)

        # 2. Release Notes Header
        self.notes_header_layout = QHBoxLayout()
        self.notes_title = StrongBodyLabel("Release Notes & Changelog:", self)
        self.notes_header_layout.addWidget(self.notes_title)
        self.notes_header_layout.addStretch()

        expected_hash = self.update_info.get("expected_hash", "")
        if expected_hash:
            self.hash_badge = CaptionLabel("SHA-256 Verified Source", self)
            self.hash_badge.setStyleSheet("color: #107C41; font-weight: bold;")
            self.notes_header_layout.addWidget(self.hash_badge)

        self.vbox.addLayout(self.notes_header_layout)

        # 3. Changelog Viewer Card
        self.changelog_card = CardWidget(self)
        c_layout = QVBoxLayout(self.changelog_card)
        c_layout.setContentsMargins(16, 14, 16, 14)
        c_layout.setSpacing(8)

        self.changelog_view = TextEdit(self.changelog_card)
        self.changelog_view.setReadOnly(True)
        self.changelog_view.setStyleSheet("""
            TextEdit, QTextEdit {
                font-family: 'Segoe UI', system-ui, sans-serif;
                font-size: 13px;
                line-height: 1.5;
                border: none;
                background-color: transparent;
            }
        """)

        raw_changelog = self.update_info.get("changelog", "").strip()
        if not raw_changelog:
            raw_changelog = "No detailed release notes provided for this release."

        self.changelog_view.setMarkdown(raw_changelog)
        c_layout.addWidget(self.changelog_view)
        self.vbox.addWidget(self.changelog_card, 1)

        # 4. Download Progress Card (Hidden initially)
        self.progress_card = CardWidget(self)
        p_layout = QVBoxLayout(self.progress_card)
        p_layout.setContentsMargins(16, 12, 16, 12)
        p_layout.setSpacing(8)

        self.progress_label = StrongBodyLabel("Downloading update package...", self.progress_card)
        self.progress_label.setWordWrap(True)
        self.progress_bar = ProgressBar(self.progress_card)
        self.progress_bar.setValue(0)

        p_info_layout = QHBoxLayout()
        self.progress_size_lbl = CaptionLabel("0 MB / 0 MB", self.progress_card)
        self.progress_speed_lbl = CaptionLabel("Speed: --", self.progress_card)
        self.progress_eta_lbl = CaptionLabel("ETA: --", self.progress_card)

        p_info_layout.addWidget(self.progress_size_lbl)
        p_info_layout.addStretch()
        p_info_layout.addWidget(self.progress_speed_lbl)
        p_info_layout.addSpacing(16)
        p_info_layout.addWidget(self.progress_eta_lbl)

        p_layout.addWidget(self.progress_label)
        p_layout.addWidget(self.progress_bar)
        p_layout.addLayout(p_info_layout)

        self.progress_card.hide()
        self.vbox.addWidget(self.progress_card)

        # 5. Asset Details
        asset_name = self.update_info.get("asset_name", "")
        asset_size = self.update_info.get("asset_size", 0)
        if asset_name and asset_size > 0:
            size_mb = asset_size / (1024 * 1024)
            self.asset_info_lbl = CaptionLabel(f"Package: {asset_name} ({size_mb:.1f} MB)", self)
            self.vbox.addWidget(self.asset_info_lbl)

        # 6. Action Buttons
        self.btn_layout = QHBoxLayout()
        self.btn_layout.setSpacing(10)

        self.btn_github = PushButton("View on GitHub", self, FIF.GLOBE)
        self.btn_github.clicked.connect(self._open_github)

        self.btn_later = PushButton("Remind Me Later", self)
        self.btn_later.clicked.connect(self.reject)

        self.btn_download = PrimaryPushButton("Download & Install Update", self, FIF.DOWNLOAD)
        self.btn_download.clicked.connect(self._start_download)

        self.btn_cancel_dl = PushButton("Cancel Download", self, FIF.CLOSE)
        self.btn_cancel_dl.clicked.connect(self._cancel_download)
        self.btn_cancel_dl.hide()

        self.btn_install_now = PrimaryPushButton("Install & Restart Now", self, FIF.UPDATE)
        self.btn_install_now.clicked.connect(self._install_and_restart)
        self.btn_install_now.hide()

        self.btn_layout.addWidget(self.btn_github)
        self.btn_layout.addStretch(1)
        self.btn_layout.addWidget(self.btn_later)
        self.btn_layout.addWidget(self.btn_download)
        self.btn_layout.addWidget(self.btn_cancel_dl)
        self.btn_layout.addWidget(self.btn_install_now)

        self.vbox.addLayout(self.btn_layout)

    def _open_github(self):
        url = self.update_info.get("html_url", "")
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _start_download(self):
        download_url = self.update_info.get("download_url", "")
        if not download_url or not download_url.startswith("http"):
            # Fallback to web browser
            html_url = self.update_info.get("html_url", "")
            if html_url:
                QDesktopServices.openUrl(QUrl(html_url))
            return

        # Switch UI to Downloading State
        self.btn_download.hide()
        self.btn_later.setEnabled(False)
        self.btn_cancel_dl.show()
        self.progress_card.show()
        self.progress_bar.setValue(0)
        self.progress_label.setText("Downloading update installer...")

        version_str = self.update_info.get("latest_version", "latest")
        asset_name = self.update_info.get("asset_name", "")
        expected_hash = self.update_info.get("expected_hash", "")

        self.download_worker = UpdateDownloadWorker(
            download_url=download_url,
            version_str=version_str,
            asset_name=asset_name,
            expected_hash=expected_hash,
            parent=self
        )
        self.download_worker.progress.connect(self._on_download_progress)
        self.download_worker.download_finished.connect(self._on_download_finished)
        self.download_worker.download_failed.connect(self._on_download_failed)
        self.download_worker.start()

    def _on_download_progress(self, downloaded, total, speed, eta_str):
        if total > 0:
            pct = int((downloaded / total) * 100)
            self.progress_bar.setValue(pct)
            self.progress_size_lbl.setText(f"{format_size(downloaded)} / {format_size(total)}")
        else:
            self.progress_size_lbl.setText(f"{format_size(downloaded)} downloaded")

        self.progress_speed_lbl.setText(f"Speed: {format_size(speed)}/s")
        self.progress_eta_lbl.setText(f"ETA: {eta_str}")

    def _on_download_finished(self, installer_path):
        self.downloaded_installer_path = installer_path

        # Switch UI to Ready to Install State
        self.progress_bar.setValue(100)
        self.progress_label.setText("Update package verified and ready for installation!")
        self.progress_speed_lbl.setText("")
        self.progress_eta_lbl.setText("")

        self.btn_cancel_dl.hide()
        self.btn_later.setEnabled(True)
        self.btn_later.setText("Install Later")
        self.btn_install_now.show()

    def _on_download_failed(self, error_msg):
        self.progress_card.hide()
        self.btn_cancel_dl.hide()
        self.btn_later.setEnabled(True)
        self.btn_download.show()
        self.btn_download.setText("Retry Download")

        InfoBar.error(
            "Download Failed",
            error_msg,
            duration=5000,
            parent=self
        )

    def _cancel_download(self):
        if self.download_worker and self.download_worker.isRunning():
            self.download_worker.cancel()
            self.download_worker.wait(2000)

        self.progress_card.hide()
        self.btn_cancel_dl.hide()
        self.btn_later.setEnabled(True)
        self.btn_download.show()

    def _install_and_restart(self):
        if not self.downloaded_installer_path or not os.path.exists(self.downloaded_installer_path):
            InfoBar.warning("Installer Missing", "The downloaded update installer could not be found.", parent=self)
            return

        success = UpdateInstaller.launch_installer(self.downloaded_installer_path)
        if success:
            self.accept()
            QApplication.instance().quit()
        else:
            InfoBar.error("Launch Failed", "Could not start the installer executable.", parent=self)

    def closeEvent(self, event):
        if self.download_worker and self.download_worker.isRunning():
            self.download_worker.cancel()
            self.download_worker.wait(1000)
        super().closeEvent(event)
