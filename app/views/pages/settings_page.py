import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QSizePolicy
)
from PyQt5.QtCore import Qt
from qfluentwidgets import (
    TitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel, LineEdit,
    PushButton, CheckBox, SpinBox, MessageBox, InfoBar, CardWidget,
    ComboBox, ScrollArea, IconWidget
)
from qfluentwidgets import FluentIcon as FIF

from app.models.database import (
    clear_download_history, reset_database, get_setting, set_setting
)
from app.common.version import __version__, APP_NAME
from app.services.updater import UpdateCheckWorker
from app.views.components.update_dialog import UpdateDialog


class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("SettingsPage")

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(40, 30, 40, 30)
        self.main_layout.setSpacing(16)

        self.title_label = TitleLabel('Settings & Preferences', self)
        self.main_layout.addWidget(self.title_label)

        # Smooth Scroll Area for Settings Sections
        self.scroll_area = ScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self.scroll_widget = QWidget()
        self.scroll_widget.setStyleSheet("QWidget { background: transparent; }")
        self.scroll_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.vbox = QVBoxLayout(self.scroll_widget)
        self.vbox.setContentsMargins(0, 0, 16, 20)
        self.vbox.setSpacing(18)

        # 1. Storage & Default Directory Card
        self._build_storage_card()

        # 2. AI & Smart Automation Card
        self._build_ai_card()

        # 3. Download Engine & Performance Card
        self._build_engine_card()

        # 4. Updates & Release Channel Card
        self._build_update_card()

        # 5. Data Management Card
        self._build_data_card()

        self.scroll_area.setWidget(self.scroll_widget)
        self.main_layout.addWidget(self.scroll_area, 1)

        # Load initial values from DB
        self.load_settings_values()

    def _build_storage_card(self):
        self.storage_card = CardWidget(self.scroll_widget)
        card_layout = QVBoxLayout(self.storage_card)
        card_layout.setContentsMargins(20, 16, 20, 16)
        card_layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)
        icon = IconWidget(FIF.FOLDER, self.storage_card)
        icon.setFixedSize(20, 20)
        title = StrongBodyLabel('Default Storage Location', self.storage_card)
        header.addWidget(icon)
        header.addWidget(title)
        header.addStretch()
        card_layout.addLayout(header)

        desc = CaptionLabel('Files downloaded without custom routing rules will be saved to this folder.', self.storage_card)
        card_layout.addWidget(desc)

        self.path_layout = QHBoxLayout()
        self.path_layout.setSpacing(10)
        self.path_input = LineEdit(self.storage_card)
        self.path_input.setReadOnly(True)
        self.path_btn = PushButton('Change Folder', self.storage_card, FIF.FOLDER)
        self.path_btn.clicked.connect(self.choose_download_dir)

        self.path_layout.addWidget(self.path_input, 1)
        self.path_layout.addWidget(self.path_btn, 0)
        card_layout.addLayout(self.path_layout)

        self.vbox.addWidget(self.storage_card)

    def _build_ai_card(self):
        self.ai_card = CardWidget(self.scroll_widget)
        card_layout = QVBoxLayout(self.ai_card)
        card_layout.setContentsMargins(20, 16, 20, 16)
        card_layout.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(10)
        icon = IconWidget(FIF.ROBOT, self.ai_card)
        icon.setFixedSize(20, 20)
        title = StrongBodyLabel('AI & Smart Automation Engine', self.ai_card)
        header.addWidget(icon)
        header.addWidget(title)
        header.addStretch()
        card_layout.addLayout(header)

        self.renaming_check = CheckBox('Enable AI Clean Renaming (strips website tracking tags, random hashes, and junk from filenames)', self.ai_card)
        self.renaming_check.stateChanged.connect(lambda s: set_setting("enable_ai_clean_renaming", "true" if s else "false"))
        card_layout.addWidget(self.renaming_check)

        self.threat_check = CheckBox('Enable Real-time Threat & Clickbait Detection (flags double extensions and suspicious binaries)', self.ai_card)
        self.threat_check.stateChanged.connect(lambda s: set_setting("enable_threat_detection", "true" if s else "false"))
        card_layout.addWidget(self.threat_check)

        self.auto_extract_check = CheckBox('Auto-Extract Archives with Discovered Passwords upon download completion', self.ai_card)
        self.auto_extract_check.stateChanged.connect(lambda s: set_setting("enable_auto_extract", "true" if s else "false"))
        card_layout.addWidget(self.auto_extract_check)

        self.vbox.addWidget(self.ai_card)

    def _build_engine_card(self):
        self.engine_card = CardWidget(self.scroll_widget)
        card_layout = QVBoxLayout(self.engine_card)
        card_layout.setContentsMargins(20, 16, 20, 16)
        card_layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)
        icon = IconWidget(FIF.SPEED_HIGH, self.engine_card)
        icon.setFixedSize(20, 20)
        title = StrongBodyLabel('Download Concurrency & Performance', self.engine_card)
        header.addWidget(icon)
        header.addWidget(title)
        header.addStretch()
        card_layout.addLayout(header)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.thread_lbl = BodyLabel('Max Concurrent Segments per Download:', self.engine_card)
        self.thread_spin = SpinBox(self.engine_card)
        self.thread_spin.setRange(1, 32)
        self.thread_spin.setFixedWidth(100)
        self.thread_spin.valueChanged.connect(lambda v: set_setting("max_threads", str(v)))

        row.addWidget(self.thread_lbl)
        row.addWidget(self.thread_spin)
        row.addStretch(1)
        card_layout.addLayout(row)

        desc = CaptionLabel('Higher segment counts provide maximum multi-part download acceleration on high-speed internet connections.', self.engine_card)
        card_layout.addWidget(desc)

        self.vbox.addWidget(self.engine_card)

    def _build_update_card(self):
        self.update_card = CardWidget(self.scroll_widget)
        card_layout = QVBoxLayout(self.update_card)
        card_layout.setContentsMargins(20, 16, 20, 16)
        card_layout.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(10)
        icon = IconWidget(FIF.SYNC, self.update_card)
        icon.setFixedSize(20, 20)
        title = StrongBodyLabel('Application Updates & Release Channel', self.update_card)
        header.addWidget(icon)
        header.addWidget(title)
        header.addStretch()
        card_layout.addLayout(header)

        up_top_row = QHBoxLayout()
        self.version_info_lbl = StrongBodyLabel(f"{APP_NAME} v{__version__}", self.update_card)
        self.check_updates_btn = PushButton('Check for Updates', self.update_card, FIF.SYNC)
        self.check_updates_btn.clicked.connect(self.check_for_updates_clicked)

        up_top_row.addWidget(self.version_info_lbl)
        up_top_row.addStretch(1)
        up_top_row.addWidget(self.check_updates_btn)
        card_layout.addLayout(up_top_row)

        # Channel Selection Row
        channel_row = QHBoxLayout()
        channel_row.setSpacing(10)
        self.channel_lbl = BodyLabel('Update Channel:', self.update_card)
        self.channel_combo = ComboBox(self.update_card)
        self.channel_combo.addItem("Stable (Recommended)", userData="stable")
        self.channel_combo.addItem("Beta (Early Access & Pre-releases)", userData="beta")
        self.channel_combo.setMinimumWidth(260)
        self.channel_combo.currentIndexChanged.connect(self._on_channel_changed)

        channel_row.addWidget(self.channel_lbl)
        channel_row.addWidget(self.channel_combo)
        channel_row.addStretch(1)
        card_layout.addLayout(channel_row)

        self.auto_check_update_cb = CheckBox('Automatically check for updates on startup', self.update_card)
        self.auto_check_update_cb.stateChanged.connect(lambda s: set_setting("auto_check_updates", "true" if s else "false"))
        card_layout.addWidget(self.auto_check_update_cb)

        self.vbox.addWidget(self.update_card)

    def _build_data_card(self):
        self.data_card = CardWidget(self.scroll_widget)
        card_layout = QVBoxLayout(self.data_card)
        card_layout.setContentsMargins(20, 16, 20, 16)
        card_layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)
        icon = IconWidget(FIF.DELETE, self.data_card)
        icon.setFixedSize(20, 20)
        title = StrongBodyLabel('Data Management & Reset', self.data_card)
        header.addWidget(icon)
        header.addWidget(title)
        header.addStretch()
        card_layout.addLayout(header)

        desc = CaptionLabel('Manage cached download history or perform a clean factory reset of application settings and routing rules.', self.data_card)
        card_layout.addWidget(desc)

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
