import os
import re

from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QApplication,
    QFileDialog
)

from PyQt5.QtCore import Qt, QUrl, QTimer

from qfluentwidgets import (
    LineEdit,
    PrimaryPushButton,
    PushButton,
    TitleLabel,
    StrongBodyLabel,
    ScrollArea,
    ToolButton,
    MessageBox,
    InfoBar
)

from qfluentwidgets import FluentIcon as FIF

from app.views.components.download_card import DownloadCard


class DownloadsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("DownloadsPage")

        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(40, 40, 40, 40)
        self.vbox.setSpacing(20)

        self.title_label = TitleLabel('Downloads', self)
        self.vbox.addWidget(self.title_label)

        self.input_hlayout = QHBoxLayout()
        self.input_hlayout.setSpacing(12)

        self.url_input = LineEdit(self)
        self.url_input.setPlaceholderText("Paste URL here or Drop a link...")
        self.url_input.setMinimumHeight(40)

        self.add_btn = PrimaryPushButton('Download', self, FIF.DOWNLOAD)
        self.add_btn.setMinimumHeight(40)
        self.add_btn.clicked.connect(self.add_download)

        self.paste_file_btn = PushButton('Paste URLs from file', self, FIF.DOCUMENT)
        self.paste_file_btn.setMinimumHeight(40)
        self.paste_file_btn.clicked.connect(self.import_urls_from_file)

        self.input_hlayout.addWidget(self.url_input, 1)
        self.input_hlayout.addWidget(self.add_btn, 0)
        self.input_hlayout.addWidget(self.paste_file_btn, 0)

        self.vbox.addLayout(self.input_hlayout)

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

        self.batch_queue = []
        self.active_batch_card = None

        self.clipboard = QApplication.clipboard()
        self.last_clipboard_text = ""
        self.clipboard.dataChanged.connect(self.check_clipboard)

        self.check_clipboard(is_startup=True)

        self.load_history()

    def load_history(self):
        from app.models.database import get_all_tasks

        try:
            tasks = get_all_tasks()

            for task in tasks:
                status = getattr(task, "status", "pending") or "pending"
                auto_start = status in ("pending", "downloading")

                card = DownloadCard(
                    task.url,
                    task.filename,
                    task.save_path,
                    task_id=task.id,
                    status=status,
                    auto_start=auto_start,
                    parent=self
                )

                card.taskFinished.connect(self.on_card_finished)
                self.scroll_layout.addWidget(card)

        except Exception:
            pass

    def check_clipboard(self, is_startup=False):
        mime_data = self.clipboard.mimeData()

        if mime_data.hasText():
            text = mime_data.text().strip()

            if text.startswith("http://") or text.startswith("https://"):
                if text == self.last_clipboard_text:
                    return

                self.last_clipboard_text = text
                self.url_input.setText(text)

                if not is_startup:
                    self.prompt_download_confirmation(text)

    def prompt_download_confirmation(self, url):
        w = MessageBox(
            'New Link Detected',
            f'Do you want to start downloading this link?\n\n{url}',
            self.window()
        )

        w.yesButton.setText('Yes, Download')
        w.cancelButton.setText('Cancel')

        if w.exec():
            QTimer.singleShot(250, self.add_download)

    def add_download(self):
        url = self.url_input.text().strip()

        if not url:
            return

        self.create_download_card(
            url,
            auto_start=True,
            status="pending",
            insert_top=True
        )

        self.url_input.clear()

    def create_download_card(self, url, auto_start=True, status="pending", insert_top=True):
        from app.models.database import create_task

        filename = url.split('/')[-1].split('?')[0] if '/' in url else 'unknown_file.bin'

        if not filename or filename == url:
            filename = "download"

        save_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        os.makedirs(save_dir, exist_ok=True)

        task_id = create_task(url, filename, save_dir)

        card = DownloadCard(
            url,
            filename,
            save_dir,
            task_id=task_id,
            status=status,
            auto_start=auto_start,
            parent=self
        )

        card.taskFinished.connect(self.on_card_finished)

        if insert_top:
            self.scroll_layout.insertWidget(0, card)
        else:
            self.scroll_layout.addWidget(card)

        return card

    def import_urls_from_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select URLs file",
            "",
            "Text files (*.txt);;All files (*)"
        )

        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            InfoBar.error(
                "Open file failed",
                str(e),
                parent=self.window()
            )
            return

        urls = re.findall(r'https?://[^\s"\'<>]+', content)

        cleaned = []
        seen = set()

        for url in urls:
            url = url.strip().rstrip('),];')

            if url not in seen:
                seen.add(url)
                cleaned.append(url)

        if not cleaned:
            InfoBar.warning(
                "No URLs found",
                "No valid http/https links were found in the file.",
                parent=self.window()
            )
            return

        self.enqueue_urls(cleaned)

        InfoBar.success(
            "Links added",
            f"{len(cleaned)} links added to download queue.",
            parent=self.window()
        )

    def enqueue_urls(self, urls):
        for url in urls:
            card = self.create_download_card(
                url,
                auto_start=False,
                status="pending",
                insert_top=False
            )

            card.batch_queued = True
            self.batch_queue.append(card)

        self.start_next_batch()

    def start_next_batch(self):
        if self.active_batch_card is not None:
            return

        while self.batch_queue:
            card = self.batch_queue.pop(0)

            self.active_batch_card = card
            card.start_download()
            return

        self.active_batch_card = None

    def on_card_finished(self, card):
        was_batch = getattr(card, "batch_queued", False)

        if card in self.batch_queue:
            self.batch_queue.remove(card)

        if card == self.active_batch_card:
            self.active_batch_card = None
            self.start_next_batch()

        elif was_batch and self.active_batch_card is None and self.batch_queue:
            self.start_next_batch()