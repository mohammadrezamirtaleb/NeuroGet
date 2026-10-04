import os
import subprocess
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QSizePolicy, QApplication
)
from PyQt5.QtCore import Qt
from qfluentwidgets import (
    TitleLabel, SubtitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel, LineEdit,
    PushButton, PrimaryPushButton, TransparentPushButton, CheckBox, SwitchButton,
    SpinBox, MessageBox, InfoBar, CardWidget, SimpleCardWidget,
    ComboBox, ScrollArea, IconWidget, isDarkTheme
)
from qfluentwidgets import FluentIcon as FIF

from app.models.database import (
    clear_download_history, reset_database, get_setting, set_setting, db_path
)
from app.common.version import __version__, APP_NAME
from app.services.updater import UpdateCheckWorker
from app.views.components.update_dialog import UpdateDialog


class SettingsPage(QWidget):
    """Windows 11 Fluent Design Settings & Preferences page.
    Configures storage paths, AI automation, acceleration parameters, notifications,
    release channels, and database diagnostics.
    """

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("SettingsPage")

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(28, 20, 28, 20)
        self.main_layout.setSpacing(16)

        # Page Header
        header_vbox = QVBoxLayout()
        header_vbox.setSpacing(2)
        self.title_label = TitleLabel('Settings & Preferences', self)
        self.title_label.setWordWrap(True)
        self.sub_title_label = CaptionLabel(
            'Configure storage locations, autonomous AI automation, acceleration engine, and system preferences.',
            self
        )
        self.sub_title_label.setWordWrap(True)
        header_vbox.addWidget(self.title_label)
        header_vbox.addWidget(self.sub_title_label)
        self.main_layout.addLayout(header_vbox)

        # Smooth Scroll Area for Settings Sections
        self.scroll_area = ScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self.scroll_widget = QWidget()
        self.scroll_widget.setStyleSheet("QWidget { background: transparent; }")
        self.scroll_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.vbox = QVBoxLayout(self.scroll_widget)
        self.vbox.setContentsMargins(0, 0, 16, 24)
        self.vbox.setSpacing(18)

        # 1. Storage & Default Directory Card
        self._build_storage_card()

        # 2. AI & Smart Automation Card
        self._build_ai_card()

        # 3. Download Engine & Performance Card
        self._build_engine_card()

        # 4. Sound & Notifications Card
        self._build_notifications_card()

        # 5. Updates & Release Channel Card
        self._build_update_card()

        # 6. Data Management & System Diagnostics Card
        self._build_data_card()

        self.scroll_area.setWidget(self.scroll_widget)
        self.main_layout.addWidget(self.scroll_area, 1)

        # Load initial values from DB
        self.load_settings_values()

    def _create_header_badge(self, parent_card, icon_type, title_text, subtitle_text=""):
        header = QHBoxLayout()
        header.setSpacing(12)

        icon_card = SimpleCardWidget(parent_card)
        icon_card.setFixedSize(36, 36)
        icon_card_layout = QVBoxLayout(icon_card)
        icon_card_layout.setContentsMargins(0, 0, 0, 0)
        icon_card_layout.setAlignment(Qt.AlignCenter)

        icon_widget = IconWidget(icon_type, icon_card)
        icon_widget.setFixedSize(20, 20)
        icon_card_layout.addWidget(icon_widget, 0, Qt.AlignCenter)

        title_vbox = QVBoxLayout()
        title_vbox.setSpacing(1)
        title_lbl = StrongBodyLabel(title_text, parent_card)
        title_vbox.addWidget(title_lbl)
        if subtitle_text:
            sub_lbl = CaptionLabel(subtitle_text, parent_card)
            sub_lbl.setWordWrap(True)
            title_vbox.addWidget(sub_lbl)

        header.addWidget(icon_card)
        header.addLayout(title_vbox, 1)
        return header

    def _build_storage_card(self):
        self.storage_card = CardWidget(self.scroll_widget)
        card_layout = QVBoxLayout(self.storage_card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(14)

        header = self._create_header_badge(
            self.storage_card,
            FIF.FOLDER,
            'Default Storage Location',
            'Files downloaded without custom category routing rules will be saved directly into this folder.'
        )
        card_layout.addLayout(header)

        self.path_layout = QHBoxLayout()
        self.path_layout.setSpacing(10)
        self.path_input = LineEdit(self.storage_card)
        self.path_input.setReadOnly(True)
        self.path_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.path_btn = PushButton('Change Folder', self.storage_card, FIF.FOLDER)
        self.path_btn.clicked.connect(self.choose_download_dir)

        self.open_folder_btn = PushButton('Open in Explorer', self.storage_card, FIF.FOLDER_ADD)
        self.open_folder_btn.clicked.connect(self._open_current_download_dir)

        self.path_layout.addWidget(self.path_input, 1)
        self.path_layout.addWidget(self.path_btn, 0)
        self.path_layout.addWidget(self.open_folder_btn, 0)
        card_layout.addLayout(self.path_layout)

        self.vbox.addWidget(self.storage_card)

    def _build_ai_card(self):
        self.ai_card = CardWidget(self.scroll_widget)
        card_layout = QVBoxLayout(self.ai_card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(14)

        header = self._create_header_badge(
            self.ai_card,
            FIF.ROBOT,
            'Autonomous AI & Smart Automation',
            'Granular controls for neural file sanitization, heuristic threat scanning, and automated extraction.'
        )
        card_layout.addLayout(header)

        # 1. AI Clean Renaming Checkbox
        self.renaming_check = CheckBox(
            'Enable AI Clean Renaming (strips website tracking tags, random hashes, and junk from filenames)',
            self.ai_card
        )
        self.renaming_check.stateChanged.connect(
            lambda s: set_setting("enable_ai_clean_renaming", "true" if s else "false")
        )
        card_layout.addWidget(self.renaming_check)

        # 2. Threat & Clickbait Detection Checkbox
        self.threat_check = CheckBox(
            'Enable Real-time Threat & Clickbait Detection (flags double extensions and suspicious binaries)',
            self.ai_card
        )
        self.threat_check.stateChanged.connect(
            lambda s: set_setting("enable_threat_detection", "true" if s else "false")
        )
        card_layout.addWidget(self.threat_check)

        # 3. Auto Extract Checkbox
        self.auto_extract_check = CheckBox(
            'Auto-Extract Archives with Discovered Passwords upon download completion',
            self.ai_card
        )
        self.auto_extract_check.stateChanged.connect(
            lambda s: set_setting("enable_auto_extract", "true" if s else "false")
        )
        card_layout.addWidget(self.auto_extract_check)

        self.vbox.addWidget(self.ai_card)

    def _build_engine_card(self):
        self.engine_card = CardWidget(self.scroll_widget)
        card_layout = QVBoxLayout(self.engine_card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(14)

        header = self._create_header_badge(
            self.engine_card,
            FIF.SPEED_HIGH,
            'Download Concurrency & Performance Engine',
            'Optimize multi-segmented throughput and socket connection thresholds.'
        )
        card_layout.addLayout(header)

        # Concurrency SpinBox Row
        thread_row = QHBoxLayout()
        thread_row.setSpacing(12)
        thread_title_vbox = QVBoxLayout()
        thread_title_vbox.setSpacing(1)
        self.thread_lbl = StrongBodyLabel('Max Concurrent Segments per Download:', self.engine_card)
        thread_desc = CaptionLabel('Splits large files into parallel dynamic byte chunks for accelerated speed.', self.engine_card)
        thread_desc.setWordWrap(True)
        thread_title_vbox.addWidget(self.thread_lbl)
        thread_title_vbox.addWidget(thread_desc)

        self.thread_spin = SpinBox(self.engine_card)
        self.thread_spin.setRange(1, 32)
        self.thread_spin.setFixedWidth(110)
        self.thread_spin.valueChanged.connect(lambda v: set_setting("max_threads", str(v)))

        thread_row.addLayout(thread_title_vbox, 1)
        thread_row.addWidget(self.thread_spin, 0)
        card_layout.addLayout(thread_row)

        # Socket Timeout Row
        timeout_row = QHBoxLayout()
        timeout_row.setSpacing(12)
        timeout_vbox = QVBoxLayout()
        timeout_vbox.setSpacing(1)
        timeout_title = StrongBodyLabel('Socket Connection Timeout:', self.engine_card)
        timeout_sub = CaptionLabel('Maximum time to wait before retrying slow server handshakes.', self.engine_card)
        timeout_sub.setWordWrap(True)
        timeout_vbox.addWidget(timeout_title)
        timeout_vbox.addWidget(timeout_sub)

        self.timeout_combo = ComboBox(self.engine_card)
        self.timeout_combo.addItem("15 Seconds (Fast Failover)", userData="15")
        self.timeout_combo.addItem("30 Seconds (Default)", userData="30")
        self.timeout_combo.addItem("60 Seconds (Lenient)", userData="60")
        self.timeout_combo.setMinimumWidth(200)
        self.timeout_combo.currentIndexChanged.connect(self._on_timeout_changed)

        timeout_row.addLayout(timeout_vbox, 1)
        timeout_row.addWidget(self.timeout_combo, 0)
        card_layout.addLayout(timeout_row)

        self.vbox.addWidget(self.engine_card)

    def _build_notifications_card(self):
        self.notify_card = CardWidget(self.scroll_widget)
        card_layout = QVBoxLayout(self.notify_card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(14)

        header = self._create_header_badge(
            self.notify_card,
            FIF.RINGER,
            'Notifications & Audio Alerts',
            'System tray popups and audio chimes when tasks conclude.'
        )
        card_layout.addLayout(header)

        self.sound_check = CheckBox('Play audio alert when a download finishes successfully', self.notify_card)
        self.sound_check.stateChanged.connect(
            lambda s: set_setting("enable_completion_sound", "true" if s else "false")
        )
        card_layout.addWidget(self.sound_check)

        self.auto_resume_check = CheckBox('Automatically resume interrupted downloads on startup', self.notify_card)
        self.auto_resume_check.stateChanged.connect(
            lambda s: set_setting("enable_auto_resume", "true" if s else "false")
        )
        card_layout.addWidget(self.auto_resume_check)

        self.vbox.addWidget(self.notify_card)

    def _build_update_card(self):
        self.update_card = CardWidget(self.scroll_widget)
        card_layout = QVBoxLayout(self.update_card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(14)

        header = self._create_header_badge(
            self.update_card,
            FIF.SYNC,
            'Application Updates & Release Channel',
            'Verify release integrity, switch beta channels, and receive seamless in-app upgrades.'
        )
        card_layout.addLayout(header)

        up_top_row = QHBoxLayout()
        up_top_row.setSpacing(12)

        ver_vbox = QVBoxLayout()
        ver_vbox.setSpacing(2)
        self.version_info_lbl = StrongBodyLabel(f"{APP_NAME} v{__version__}", self.update_card)
        self.ver_status_badge = CaptionLabel("Official Build", self.update_card)
        self.ver_status_badge.setStyleSheet("""
            CaptionLabel {
                color: #0078D4;
                background-color: rgba(0, 120, 212, 0.12);
                border: 1px solid rgba(0, 120, 212, 0.25);
                border-radius: 4px;
                padding: 1px 7px;
                font-weight: 600;
                font-size: 11px;
            }
        """)
        ver_row = QHBoxLayout()
        ver_row.addWidget(self.version_info_lbl)
        ver_row.addWidget(self.ver_status_badge)
        ver_row.addStretch()
        ver_vbox.addLayout(ver_row)

        self.check_updates_btn = PrimaryPushButton('Check for Updates', self.update_card, FIF.SYNC)
        self.check_updates_btn.clicked.connect(self.check_for_updates_clicked)

        up_top_row.addLayout(ver_vbox, 1)
        up_top_row.addWidget(self.check_updates_btn, 0)
        card_layout.addLayout(up_top_row)

        # Channel Selection Row
        channel_row = QHBoxLayout()
        channel_row.setSpacing(10)
        self.channel_lbl = BodyLabel('Update Channel:', self.update_card)
        self.channel_combo = ComboBox(self.update_card)
        self.channel_combo.addItem("Stable (Recommended)", userData="stable")
        self.channel_combo.addItem("Beta (Early Access & Pre-releases)", userData="beta")
        self.channel_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.channel_combo.setMinimumWidth(220)
        self.channel_combo.currentIndexChanged.connect(self._on_channel_changed)

        channel_row.addWidget(self.channel_lbl)
        channel_row.addWidget(self.channel_combo, 1)
        card_layout.addLayout(channel_row)

        self.auto_check_update_cb = CheckBox('Automatically check for updates on startup', self.update_card)
        self.auto_check_update_cb.stateChanged.connect(
            lambda s: set_setting("auto_check_updates", "true" if s else "false")
        )
        card_layout.addWidget(self.auto_check_update_cb)

        self.vbox.addWidget(self.update_card)

    def _build_data_card(self):
        self.data_card = CardWidget(self.scroll_widget)
        card_layout = QVBoxLayout(self.data_card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(14)

        header = self._create_header_badge(
            self.data_card,
            FIF.DELETE,
            'Database & Diagnostics Management',
            'Inspect SQLite storage location or perform a safe history cleanup / full factory reset.'
        )
        card_layout.addLayout(header)

        # DB location caption
        clean_db_path = db_path.replace("\\", "/")
        db_label = CaptionLabel(f"SQLite Storage: {clean_db_path}", self.data_card)
        db_label.setWordWrap(True)
        card_layout.addWidget(db_label)

        self.data_layout = QHBoxLayout()
        self.data_layout.setSpacing(10)

        self.clear_history_btn = PushButton('Clear Download History', self.data_card, FIF.DELETE)
        self.clear_history_btn.clicked.connect(self.prompt_clear_history)

        self.reset_db_btn = PushButton('Factory Reset Database', self.data_card, FIF.DELETE)
        self.reset_db_btn.clicked.connect(self.prompt_reset_database)

        self.data_layout.addWidget(self.clear_history_btn)
        self.data_layout.addWidget(self.reset_db_btn)
        self.data_layout.addStretch(1)
        card_layout.addLayout(self.data_layout)

        self.vbox.addWidget(self.data_card)

    def choose_download_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Default Download Directory")
        if folder:
            self.path_input.setText(folder)
            set_setting("default_download_dir", folder)
            InfoBar.success("Folder Updated", f"Default download directory set to:\n{folder}", parent=self.window())

    def _open_current_download_dir(self):
        current = self.path_input.text().strip()
        if current and os.path.exists(current):
            try:
                os.startfile(current)
            except Exception:
                subprocess.Popen(['explorer', current])
        else:
            InfoBar.warning("Folder Missing", "The specified folder does not exist on disk.", parent=self.window())

    def prompt_clear_history(self):
        w = MessageBox(
            'Clear History',
            'Are you sure you want to delete all completed download tasks from the history? This will not delete the actual downloaded files on your disk.',
            self.window()
        )
        if w.exec():
            clear_download_history()
            InfoBar.success('Success', 'Download history has been cleared.', parent=self.window())

    def load_settings_values(self):
        """Syncs all settings UI controls with the current database values."""
        default_dir = get_setting("default_download_dir", os.path.join(os.path.expanduser("~"), "Downloads"))
        self.path_input.setText(default_dir)

        is_rename = get_setting("enable_ai_clean_renaming", "true").lower() in ("true", "1", "yes")
        self.renaming_check.blockSignals(True)
        self.renaming_check.setChecked(is_rename)
        self.renaming_check.blockSignals(False)

        is_threat = get_setting("enable_threat_detection", "true").lower() in ("true", "1", "yes")
        self.threat_check.blockSignals(True)
        self.threat_check.setChecked(is_threat)
        self.threat_check.blockSignals(False)

        is_extract = get_setting("enable_auto_extract", "false").lower() in ("true", "1", "yes")
        self.auto_extract_check.blockSignals(True)
        self.auto_extract_check.setChecked(is_extract)
        self.auto_extract_check.blockSignals(False)

        saved_threads = int(get_setting("max_threads", "16"))
        self.thread_spin.blockSignals(True)
        self.thread_spin.setValue(saved_threads)
        self.thread_spin.blockSignals(False)

        saved_timeout = get_setting("socket_timeout", "30")
        self.timeout_combo.blockSignals(True)
        t_idx = 1
        if saved_timeout == "15":
            t_idx = 0
        elif saved_timeout == "60":
            t_idx = 2
        self.timeout_combo.setCurrentIndex(t_idx)
        self.timeout_combo.blockSignals(False)

        is_sound = get_setting("enable_completion_sound", "true").lower() in ("true", "1", "yes")
        self.sound_check.blockSignals(True)
        self.sound_check.setChecked(is_sound)
        self.sound_check.blockSignals(False)

        is_resume = get_setting("enable_auto_resume", "true").lower() in ("true", "1", "yes")
        self.auto_resume_check.blockSignals(True)
        self.auto_resume_check.setChecked(is_resume)
        self.auto_resume_check.blockSignals(False)

        saved_channel = get_setting("update_channel", "stable").lower()
        self.channel_combo.blockSignals(True)
        self.channel_combo.setCurrentIndex(1 if saved_channel == "beta" else 0)
        self.channel_combo.blockSignals(False)

        is_auto_check = get_setting("auto_check_updates", "true").lower() in ("true", "1", "yes")
        self.auto_check_update_cb.blockSignals(True)
        self.auto_check_update_cb.setChecked(is_auto_check)
        self.auto_check_update_cb.blockSignals(False)

    def prompt_reset_database(self):
        w = MessageBox(
            'Reset Database',
            'WARNING: This will completely wipe all download tasks, smart rules, and settings from the database. This action cannot be undone.\n\nAre you sure you want to proceed?',
            self.window()
        )
        w.yesButton.setText('Yes, Factory Reset')
        w.cancelButton.setText('Cancel')
        if w.exec():
            reset_database()
            self.load_settings_values()
            InfoBar.success('Reset Complete', 'Database has been factory reset successfully.', parent=self.window())

    def _on_timeout_changed(self, index):
        val = self.timeout_combo.itemData(index) or "30"
        set_setting("socket_timeout", val)

    def _on_channel_changed(self, index):
        channel = self.channel_combo.itemData(index) or ("beta" if index == 1 else "stable")
        set_setting("update_channel", channel)
        InfoBar.info(
            "Channel Changed",
            f"Update channel set to: {channel.capitalize()}",
            duration=3000,
            parent=self.window()
        )

    def check_for_updates_clicked(self):
        self.check_updates_btn.setEnabled(False)
        self.check_updates_btn.setText('Checking...')

        channel = get_setting("update_channel", "stable")
        self.update_worker = UpdateCheckWorker(current_version=__version__, channel=channel, parent=self)
        self.update_worker.finished_check.connect(self._on_update_checked)
        self.update_worker.failed_check.connect(self._on_update_failed)
        self.update_worker.start()

    def _on_update_checked(self, info: dict):
        self.check_updates_btn.setEnabled(True)
        self.check_updates_btn.setText('Check for Updates')

        if info.get("has_update"):
            dialog = UpdateDialog(info, parent=self.window())
            dialog.exec_()
        else:
            InfoBar.success(
                'Up to Date',
                f'{APP_NAME} is already running the latest version (v{__version__}).',
                parent=self.window()
            )

    def _on_update_failed(self, error_msg: str):
        self.check_updates_btn.setEnabled(True)
        self.check_updates_btn.setText('Check for Updates')
        InfoBar.warning(
            'Update Check Failed',
            f'Unable to check for updates: {error_msg}',
            parent=self.window()
        )
