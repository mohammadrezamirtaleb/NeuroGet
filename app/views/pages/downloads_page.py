from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QApplication
from PyQt5.QtCore import Qt, QUrl
from qfluentwidgets import (LineEdit, PrimaryPushButton, TitleLabel, 
                            StrongBodyLabel, ScrollArea, ToolButton, MessageBox)
from qfluentwidgets import FluentIcon as FIF

from app.views.components.download_card import DownloadCard

class DownloadsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("DownloadsPage")
        
        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(40, 40, 40, 40)
        self.vbox.setSpacing(20)
        
        # Title
        self.title_label = TitleLabel('Downloads', self)
        self.vbox.addWidget(self.title_label)
        
        # URL Input Area
        self.input_hlayout = QHBoxLayout()
        self.input_hlayout.setSpacing(12)
        
        self.url_input = LineEdit(self)
        self.url_input.setPlaceholderText("Paste URL here or Drop a link...")
        self.url_input.setMinimumHeight(40)
        
        self.add_btn = PrimaryPushButton('Download', self, FIF.DOWNLOAD)
        self.add_btn.setMinimumHeight(40)
        self.add_btn.clicked.connect(self.add_download)
        
        self.input_hlayout.addWidget(self.url_input, 1)
        self.input_hlayout.addWidget(self.add_btn, 0)
        
        self.vbox.addLayout(self.input_hlayout)
        
        # Scroll Area for Downloads
        self.scroll_area = ScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("QScrollArea {background: transparent; border: none;}")
        
        self.scroll_widget = QWidget()
        self.scroll_widget.setStyleSheet("QWidget {background: transparent;}")
        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        self.scroll_layout.setAlignment(Qt.AlignTop)
        self.scroll_layout.setSpacing(10)
        
        self.scroll_area.setWidget(self.scroll_widget)
        self.vbox.addWidget(self.scroll_area)
        
        # --- Clipboard Auto-Detect ---
        self.clipboard = QApplication.clipboard()
        self.last_clipboard_text = ""
        self.clipboard.dataChanged.connect(self.check_clipboard)
        
        # Initial check on startup
        self.check_clipboard(is_startup=True)

    def check_clipboard(self, is_startup=False):
        mime_data = self.clipboard.mimeData()
        if mime_data.hasText():
            text = mime_data.text().strip()
            
            # Basic URL validation
            if text.startswith("http://") or text.startswith("https://"):
                if text == self.last_clipboard_text:
                    return
                
                self.last_clipboard_text = text
                
                # If the app just started, fill the box but don't force a popup (less annoying)
                # If they copy while app is running, ask for confirmation
                if is_startup:
                    self.url_input.setText(text)
                else:
                    self.url_input.setText(text)
                    self.prompt_download_confirmation(text)

    def prompt_download_confirmation(self, url):
        # Create a fluent message box for user confirmation
        w = MessageBox(
            'New Link Detected',
            f'Do you want to start downloading this link?\n\n{url}',
            self.window()
        )
        w.yesButton.setText('Yes, Download')
        w.cancelButton.setText('Cancel')

        if w.exec():
            self.add_download()

    def add_download(self):
        url = self.url_input.text().strip()
        if not url: return
        filename = url.split('/')[-1].split('?')[0] if '/' in url else 'unknown_file.bin'
        if not filename or filename == url: filename = "download"
        
        import os
        from app.models.database import create_task
        
        save_dir = os.path.expanduser("~\\Downloads")
        os.makedirs(save_dir, exist_ok=True)
        
        # Save to Database First
        task_id = create_task(url, filename, save_dir)
        
        card = DownloadCard(url, filename, save_dir, task_id=task_id, parent=self)
        self.scroll_layout.insertWidget(0, card)
        self.url_input.clear()
