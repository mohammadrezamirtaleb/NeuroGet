import os
import sys
import webbrowser
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QSizePolicy
)
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices
from qfluentwidgets import (
    TitleLabel, SubtitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton, CardWidget, SimpleCardWidget,
    IconWidget, ImageLabel, ScrollArea, InfoBar
)
from qfluentwidgets import FluentIcon as FIF

from app.common.version import __version__, APP_NAME
from app.services.updater import UpdateCheckWorker
from app.views.components.update_dialog import UpdateDialog
from app.models.database import get_setting


def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), relative_path)


class AboutPage(QWidget):
    """Windows 11 Fluent Design About Page showcasing NeuroGet architecture,
    developer credits, open-source community links, and feature highlights.
    """

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("AboutPage")

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(32, 24, 32, 24)
        self.main_layout.setSpacing(18)

        # Smooth Scroll Area
        self.scroll_area = ScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self.scroll_widget = QWidget()
        self.scroll_widget.setStyleSheet("QWidget { background: transparent; }")
        self.scroll_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.vbox = QVBoxLayout(self.scroll_widget)
        self.vbox.setContentsMargins(0, 0, 12, 24)
        self.vbox.setSpacing(22)

        # 1. Hero Header Card
        self._build_hero_card()

        # 2. Mission & Overview Card
        self._build_overview_card()

        # 3. Core Feature Highlights (Bento Grid)
        self._build_features_grid()

        # 4. Open-Source Community & Developer Card
        self._build_developer_card()

        # 5. Technology Stack & Privacy Commitment Card
        self._build_tech_card()

        self.scroll_area.setWidget(self.scroll_widget)
        self.main_layout.addWidget(self.scroll_area, 1)

    def _build_hero_card(self):
        hero_card = CardWidget(self.scroll_widget)
        h_layout = QHBoxLayout(hero_card)
        h_layout.setContentsMargins(28, 24, 28, 24)
        h_layout.setSpacing(24)

        # App Logo / Icon container
        icon_card = SimpleCardWidget(hero_card)
        icon_card.setFixedSize(68, 68)
        icon_card_layout = QVBoxLayout(icon_card)
        icon_card_layout.setContentsMargins(0, 0, 0, 0)
        icon_card_layout.setAlignment(Qt.AlignCenter)

        logo_file = resource_path("assets/logo_transparent.png")
        if os.path.exists(logo_file):
            logo_img = ImageLabel(logo_file, icon_card)
            logo_img.setFixedSize(54, 54)
            logo_img.scaledToWidth(54)
            icon_card_layout.addWidget(logo_img, 0, Qt.AlignCenter)
        else:
            hero_icon = IconWidget(FIF.ROBOT, icon_card)
            hero_icon.setFixedSize(38, 38)
            icon_card_layout.addWidget(hero_icon, 0, Qt.AlignCenter)

        h_layout.addWidget(icon_card)

        # Titles and version badge
        title_vbox = QVBoxLayout()
        title_vbox.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(12)
        app_title = TitleLabel(APP_NAME, hero_card)
        
        ver_badge = CaptionLabel(f"v{__version__} Official Release", hero_card)
        ver_badge.setStyleSheet("""
            CaptionLabel {
                color: #0078D4;
                background-color: rgba(0, 120, 212, 0.12);
                border: 1px solid rgba(0, 120, 212, 0.25);
                border-radius: 5px;
                padding: 2px 8px;
                font-weight: 600;
                font-size: 11px;
            }
        """)

        top_row.addWidget(app_title)
        top_row.addWidget(ver_badge)
        top_row.addStretch()
        title_vbox.addLayout(top_row)

        tagline = BodyLabel(
            "Next-Generation AI-Driven Download Acceleration and Document Knowledge Hub for Windows 11.",
            hero_card
        )
        tagline.setWordWrap(True)
        title_vbox.addWidget(tagline)

        h_layout.addLayout(title_vbox, 1)
        self.vbox.addWidget(hero_card)

    def _build_overview_card(self):
        card = CardWidget(self.scroll_widget)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 20, 24, 20)
        card_layout.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(12)
        icon = IconWidget(FIF.APPLICATION, card)
        icon.setFixedSize(20, 20)
        title = StrongBodyLabel("About NeuroGet", card)
        header.addWidget(icon)
        header.addWidget(title)
        header.addStretch()
        card_layout.addLayout(header)

        desc = BodyLabel(
            "NeuroGet redefines traditional file management by fusing high-speed multi-threaded "
            "download acceleration with autonomous local and cloud AI intelligence. Built from the ground up "
            "with Windows 11 Fluent Design principles, NeuroGet categorizes incoming files into semantic directories, "
            "cleans junk tracking tags from filenames, performs real-time heuristic threat detection, and enables "
            "instant conversational Q&A with downloaded documents and archives.",
            card
        )
        desc.setWordWrap(True)
        card_layout.addWidget(desc)

        self.vbox.addWidget(card)

    def _build_features_grid(self):
        grid_container = QWidget(self.scroll_widget)
        grid = QGridLayout(grid_container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(16)

        features = [
            (
                FIF.ROBOT,
                "Autonomous AI Routing",
                "Classifies files and URLs into smart categories (Documents, Code, Media, Software) using local Ollama models or cloud AI."
            ),
            (
                FIF.SPEED_HIGH,
                "Multi-Segment Acceleration",
                "Splits downloads into up to 32 parallel dynamic byte segments with robust pause, resume, and socket failover."
            ),
            (
                FIF.DOCUMENT,
                "Document Intelligence (Mini-RAG)",
                "Instant offline semantic summarization, key takeaway extraction, and interactive Q&A directly with downloaded files."
            ),
            (
                FIF.ACCEPT,
                "Threat & Clickbait Shield",
                "Inspects incoming URLs and file extensions to flag double-extension exploits, clickbait payloads, and risky binaries."
            ),
            (
                FIF.ZIP_FOLDER,
                "Smart Archive Unpacker",
                "Discovers extraction passwords from download sources and automatically unpacks archives with Zip-Slip path validation."
            ),
            (
                FIF.TILES,
                "Native Fluent Experience",
                "Fully responsive Windows 11 Fluent interface with dark/light theme switching, acrylic textures, and seamless DPI scaling."
            )
        ]

        for idx, (icon_type, feat_title, feat_desc) in enumerate(features):
            row = idx // 2
            col = idx % 2

            item_card = SimpleCardWidget(grid_container)
            item_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            item_layout = QVBoxLayout(item_card)
            item_layout.setContentsMargins(20, 18, 20, 18)
            item_layout.setSpacing(10)

            head_row = QHBoxLayout()
            head_row.setSpacing(10)
            f_icon = IconWidget(icon_type, item_card)
            f_icon.setFixedSize(20, 20)
            f_title = StrongBodyLabel(feat_title, item_card)
            f_title.setWordWrap(True)
            head_row.addWidget(f_icon)
            head_row.addWidget(f_title, 1)
            item_layout.addLayout(head_row)

            f_body = CaptionLabel(feat_desc, item_card)
            f_body.setWordWrap(True)
            item_layout.addWidget(f_body)

            grid.addWidget(item_card, row, col)

        self.vbox.addWidget(grid_container)

    def _build_developer_card(self):
        card = CardWidget(self.scroll_widget)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 20, 24, 20)
        card_layout.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(12)
        icon = IconWidget(FIF.GITHUB, card)
        icon.setFixedSize(20, 20)
        title = StrongBodyLabel("Open Source & Community", card)
        header.addWidget(icon)
        header.addWidget(title)
        header.addStretch()
        card_layout.addLayout(header)

        dev_desc = BodyLabel(
            "NeuroGet is developed as an open-source project by Mohammadreza Mirtaleb. "
            "Contributions, feature requests, and community feedback are always welcome.",
            card
        )
        dev_desc.setWordWrap(True)
        card_layout.addWidget(dev_desc)

        # Interactive Community Action Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self.btn_github = PrimaryPushButton("GitHub Repository", card, FIF.GITHUB)
        self.btn_github.setMinimumHeight(36)
        self.btn_github.clicked.connect(lambda: self._open_url("https://github.com/mohammadrezamirtaleb/NeuroGet"))

        self.btn_issues = PushButton("Report an Issue", card, FIF.FEEDBACK)
        self.btn_issues.setMinimumHeight(36)
        self.btn_issues.clicked.connect(lambda: self._open_url("https://github.com/mohammadrezamirtaleb/NeuroGet/issues"))

        self.btn_updates = PushButton("Check for Updates", card, FIF.SYNC)
        self.btn_updates.setMinimumHeight(36)
        self.btn_updates.clicked.connect(self._check_updates)

        btn_row.addWidget(self.btn_github)
        btn_row.addWidget(self.btn_issues)
        btn_row.addWidget(self.btn_updates)
        btn_row.addStretch()

        card_layout.addLayout(btn_row)
        self.vbox.addWidget(card)

    def _build_tech_card(self):
        card = CardWidget(self.scroll_widget)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 20, 24, 20)
        card_layout.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(12)
        icon = IconWidget(FIF.CODE, card)
        icon.setFixedSize(20, 20)
        title = StrongBodyLabel("Engine Specifications & Privacy Commitment", card)
        header.addWidget(icon)
        header.addWidget(title)
        header.addStretch()
        card_layout.addLayout(header)

        tech_desc = CaptionLabel(
            "• Core Architecture: Python 3.11 & Qt5 (PyQt5) Engine\n"
            "• Design System: Microsoft Fluent Design System via QFluentWidgets\n"
            "• AI Engines: Ollama (Local/Offline LLMs), OpenAI, Google Gemini, Anthropic, OpenRouter\n"
            "• Storage & Cache: SQLite 3 with SQLAlchemy ORM\n"
            "• Privacy Commitment: 100% Client-Side Privacy. Your files and download URLs never leave your machine.",
            card
        )
        tech_desc.setWordWrap(True)
        card_layout.addWidget(tech_desc)

        self.vbox.addWidget(card)

    def _open_url(self, url: str):
        try:
            QDesktopServices.openUrl(QUrl(url))
        except Exception:
            webbrowser.open(url)

    def _check_updates(self):
        self.btn_updates.setEnabled(False)
        self.btn_updates.setText("Checking...")

        channel = get_setting("update_channel", "stable")
        self.update_worker = UpdateCheckWorker(current_version=__version__, channel=channel, parent=self)
        self.update_worker.finished_check.connect(self._on_update_checked)
        self.update_worker.failed_check.connect(self._on_update_failed)
        self.update_worker.start()

    def _on_update_checked(self, info: dict):
        self.btn_updates.setEnabled(True)
        self.btn_updates.setText("Check for Updates")

        if info.get("has_update"):
            dialog = UpdateDialog(info, parent=self.window())
            dialog.exec_()
        else:
            InfoBar.success(
                'Up to Date',
                f'{APP_NAME} is already running the latest version (v{__version__}).',
                parent=self.window(),
                duration=3500
            )

    def _on_update_failed(self, error_msg: str):
        self.btn_updates.setEnabled(True)
        self.btn_updates.setText("Check for Updates")
        InfoBar.warning(
            'Update Check Failed',
            f'Unable to check for updates: {error_msg}',
            parent=self.window(),
            duration=4000
        )
