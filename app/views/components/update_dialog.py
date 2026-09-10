import webbrowser
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget, QTextEdit, QSizePolicy
)
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices
from qfluentwidgets import (
    TitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton, CardWidget, IconWidget
)
from qfluentwidgets import FluentIcon as FIF

from app.common.version import APP_NAME, __version__

class UpdateDialog(QDialog):
    """Modern Windows 11 Fluent Design dialog displaying update details, changelogs,

    and one-click download/install actions.
    """

    def __init__(self, update_info: dict, parent=None):
        super().__init__(parent)
        self.update_info = update_info
        self.setWindowTitle(f"{APP_NAME} - Software Update Available")
        self.setMinimumSize(560, 480)
        self.resize(600, 520)

        self._init_ui()

    def _init_ui(self):
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(28, 24, 28, 24)
        vbox.setSpacing(16)

        # 1. Header Card
        header_card = CardWidget(self)
        h_layout = QHBoxLayout(header_card)
        h_layout.setContentsMargins(16, 14, 16, 14)
        h_layout.setSpacing(16)

        icon_widget = IconWidget(FIF.SYNC, header_card)
        icon_widget.setFixedSize(36, 36)
        h_layout.addWidget(icon_widget)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        
        latest_ver = self.update_info.get("latest_version", "New")
        current_ver = self.update_info.get("current_version", __version__)
        
        main_title = TitleLabel(f"A new version of {APP_NAME} is available!", header_card)
        version_sub = CaptionLabel(f"Current version: v{current_ver}   →   New version: v{latest_ver}", header_card)
        
        title_col.addWidget(main_title)
        title_col.addWidget(version_sub)
        h_layout.addLayout(title_col, 1)

        vbox.addWidget(header_card)

        # 2. Release Notes & Changelog Title
        vbox.addWidget(StrongBodyLabel("Release Notes & Changelog:", self))

        # 3. Changelog Viewer
        self.changelog_view = QTextEdit(self)
        self.changelog_view.setReadOnly(True)
        self.changelog_view.setStyleSheet("""
            QTextEdit {
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
                line-height: 1.5;
                padding: 12px;
                border-radius: 8px;
            }
        """)

        raw_changelog = self.update_info.get("changelog", "").strip()
        if not raw_changelog:
            raw_changelog = "No detailed release notes provided for this release."
        
        self.changelog_view.setMarkdown(raw_changelog)
        vbox.addWidget(self.changelog_view, 1)

        # 4. Asset Details (if installer binary is available)
        asset_name = self.update_info.get("asset_name", "")
        asset_size = self.update_info.get("asset_size", 0)
        if asset_name and asset_size > 0:
            size_mb = asset_size / (1024 * 1024)
            asset_info_lbl = CaptionLabel(f"Installer: {asset_name} ({size_mb:.1f} MB)", self)
            vbox.addWidget(asset_info_lbl)

        # 5. Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_github = PushButton("View on GitHub", self, FIF.GLOBE)
        self.btn_github.clicked.connect(self._open_github)

        self.btn_later = PushButton("Remind Me Later", self)
        self.btn_later.clicked.connect(self.reject)

        self.btn_download = PrimaryPushButton("Download Update", self, FIF.DOWNLOAD)
        self.btn_download.clicked.connect(self._download_update)

        btn_layout.addWidget(self.btn_github)
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.btn_later)
        btn_layout.addWidget(self.btn_download)

        vbox.addLayout(btn_layout)

    def _open_github(self):
        url = self.update_info.get("html_url", "")
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _download_update(self):
        download_url = self.update_info.get("download_url", "")
        if download_url:
            QDesktopServices.openUrl(QUrl(download_url))
            self.accept()
