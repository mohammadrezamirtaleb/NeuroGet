import os
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog
from PyQt5.QtCore import Qt
from qfluentwidgets import (
    TitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel, LineEdit, 
    PushButton, CheckBox, SpinBox, MessageBox, InfoBar, CardWidget
)
from qfluentwidgets import FluentIcon as FIF

from app.models.database import (
    clear_download_history, reset_database, get_setting, set_setting
)

class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("SettingsPage")
        
        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(40, 30, 40, 30)
        self.vbox.setSpacing(20)
        
        self.title_label = TitleLabel('Settings & Preferences', self)
        self.vbox.addWidget(self.title_label)
        
        # 1. General Settings
        self.gen_label = StrongBodyLabel('General & Storage', self)
        self.vbox.addWidget(self.gen_label)
        
        self.path_layout = QHBoxLayout()
        default_dir = get_setting("default_download_dir", os.path.join(os.path.expanduser("~"), "Downloads"))
        self.path_input = LineEdit(self)
        self.path_input.setText(default_dir)
        self.path_input.setReadOnly(True)
        self.path_btn = PushButton('Change Folder', self, FIF.FOLDER)
        self.path_btn.clicked.connect(self.choose_download_dir)
        
        self.path_layout.addWidget(self.path_input, 1)
        self.path_layout.addWidget(self.path_btn, 0)
        self.vbox.addLayout(self.path_layout)
        
        # 2. AI & Smart Automation Settings
        self.ai_section_label = StrongBodyLabel('AI & Smart Automation Engine', self)
        self.vbox.addWidget(self.ai_section_label)

        self.ai_card = CardWidget(self)
        ai_layout = QVBoxLayout(self.ai_card)
        ai_layout.setContentsMargins(16, 14, 16, 14)
        ai_layout.setSpacing(12)

        self.renaming_check = CheckBox('Enable AI Clean Renaming (cleans website tags and hashes from filenames)', self.ai_card)
        is_rename = get_setting("enable_ai_clean_renaming", "true").lower() in ("true", "1", "yes")
        self.renaming_check.setChecked(is_rename)
        self.renaming_check.stateChanged.connect(lambda s: set_setting("enable_ai_clean_renaming", "true" if s else "false"))
        ai_layout.addWidget(self.renaming_check)

        self.threat_check = CheckBox('Enable Real-time Threat & Clickbait Detection (flags double extensions and disguised executables)', self.ai_card)
        is_threat = get_setting("enable_threat_detection", "true").lower() in ("true", "1", "yes")
        self.threat_check.setChecked(is_threat)
        self.threat_check.stateChanged.connect(lambda s: set_setting("enable_threat_detection", "true" if s else "false"))
        ai_layout.addWidget(self.threat_check)

        self.auto_extract_check = CheckBox('Auto-Extract Archives with Discovered Passwords upon download completion', self.ai_card)
        is_extract = get_setting("enable_auto_extract", "false").lower() in ("true", "1", "yes")
        self.auto_extract_check.setChecked(is_extract)
        self.auto_extract_check.stateChanged.connect(lambda s: set_setting("enable_auto_extract", "true" if s else "false"))
        ai_layout.addWidget(self.auto_extract_check)

        self.vbox.addWidget(self.ai_card)
        
        # 3. Download Engine Settings
        self.engine_label = StrongBodyLabel('Download Engine & Concurrency', self)
        self.vbox.addWidget(self.engine_label)
        
        self.thread_layout = QHBoxLayout()
        self.thread_lbl = StrongBodyLabel('Max Concurrent Segments per Download:', self)
        self.thread_spin = SpinBox(self)
        self.thread_spin.setRange(1, 32)
        saved_threads = int(get_setting("max_threads", "16"))
        self.thread_spin.setValue(saved_threads)
        self.thread_spin.valueChanged.connect(lambda v: set_setting("max_threads", str(v)))
        
        self.thread_layout.addWidget(self.thread_lbl)
        self.thread_layout.addWidget(self.thread_spin)
        self.thread_layout.addStretch(1)
        self.vbox.addLayout(self.thread_layout)
        
        # 4. Data Management Settings
        self.data_label = StrongBodyLabel('Data Management', self)
        self.vbox.addWidget(self.data_label)
        
        self.data_layout = QHBoxLayout()
        
        self.clear_history_btn = PushButton('Clear Download History', self, FIF.DELETE)
        self.clear_history_btn.clicked.connect(self.prompt_clear_history)
        
        self.reset_db_btn = PushButton('Reset Database (Factory Reset)', self, FIF.SYNC)
        self.reset_db_btn.clicked.connect(self.prompt_reset_database)
        
        self.data_layout.addWidget(self.clear_history_btn)
        self.data_layout.addWidget(self.reset_db_btn)
        self.data_layout.addStretch(1)
        self.vbox.addLayout(self.data_layout)
        
        self.vbox.addStretch(1)

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
            InfoBar.success('Reset Complete', 'Database has been factory reset successfully.', parent=self.window())
