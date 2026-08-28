from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from PyQt5.QtCore import Qt
from qfluentwidgets import (TitleLabel, StrongBodyLabel, LineEdit, 
                            PushButton, CheckBox, SpinBox, MessageBox, InfoBar)
from qfluentwidgets import FluentIcon as FIF

from app.models.database import clear_download_history, reset_database

class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("SettingsPage")
        
        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(40, 40, 40, 40)
        self.vbox.setSpacing(24)
        
        self.title_label = TitleLabel('Settings', self)
        self.vbox.addWidget(self.title_label)
        
        # General Settings
        self.gen_label = StrongBodyLabel('General', self)
        self.vbox.addWidget(self.gen_label)
        
        self.path_layout = QHBoxLayout()
        self.path_input = LineEdit(self)
        self.path_input.setText("C:\\Users\\Default\\Downloads")
        self.path_input.setReadOnly(True)
        self.path_btn = PushButton('Browse', self, FIF.FOLDER)
        
        self.path_layout.addWidget(self.path_input, 1)
        self.path_layout.addWidget(self.path_btn, 0)
        self.vbox.addLayout(self.path_layout)
        
        self.startup_check = CheckBox('Start with Windows', self)
        self.vbox.addWidget(self.startup_check)
        
        # Engine Settings
        self.engine_label = StrongBodyLabel('Download Engine', self)
        self.vbox.addWidget(self.engine_label)
        
        self.thread_layout = QHBoxLayout()
        self.thread_lbl = StrongBodyLabel('Max Concurrent Threads:', self)
        self.thread_spin = SpinBox(self)
        self.thread_spin.setRange(1, 32)
        self.thread_spin.setValue(16)
        
        self.thread_layout.addWidget(self.thread_lbl)
        self.thread_layout.addWidget(self.thread_spin)
        self.thread_layout.addStretch(1)
        self.vbox.addLayout(self.thread_layout)
        
        # Data Management Settings
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
            '⚠️ Reset Database',
            'WARNING: This will completely wipe all download tasks, smart rules, and settings from the database. This action cannot be undone.\n\nAre you sure you want to proceed?',
            self.window()
        )
        w.yesButton.setText('Yes, Factory Reset')
        w.cancelButton.setText('Cancel')
        if w.exec():
            reset_database()
            InfoBar.success('Reset Complete', 'Database has been factory reset successfully.', parent=self.window())
