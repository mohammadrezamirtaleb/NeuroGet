import os
import re
import urllib.parse

from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QApplication,
    QFileDialog,
    QDialog,
    QSizePolicy
)

from PyQt5.QtCore import Qt, QUrl, QTimer, QThread, pyqtSignal

from qfluentwidgets import (
    LineEdit,
    PrimaryPushButton,
    PushButton,
    TransparentPushButton,
    TitleLabel,
    StrongBodyLabel,
    BodyLabel,
    CaptionLabel,
    ScrollArea,
    ToolButton,
    MessageBox,
    InfoBar,
    InfoBarPosition,
    CardWidget,
    SimpleCardWidget,
    IconWidget
)

from qfluentwidgets import FluentIcon as FIF

from app.views.components.download_card import DownloadCard
from app.views.components.update_dialog import UpdateDialog
from app.services.router import SmartRouter
from app.services.ai_client import AIClient
from app.services.updater import UpdateCheckWorker
from app.common.version import __version__, APP_NAME
from app.models.database import create_task, get_all_tasks, get_setting


class NLPromptWorker(QThread):
    resolved = pyqtSignal(dict)

    def __init__(self, prompt, parent=None):
        super().__init__(parent)
        self.prompt = prompt

    def run(self):
        res = AIClient.resolve_natural_language_download(self.prompt)
        self.resolved.emit(res or {})


class DownloadsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("DownloadsPage")

        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(28, 20, 28, 20)
        self.vbox.setSpacing(16)

        self.header_layout = QHBoxLayout()
        self.header_layout.setSpacing(12)
        self.title_label = TitleLabel('Downloads', self)
        self.title_label.setWordWrap(True)
        self.update_btn = PushButton('Check for Updates', self, FIF.UPDATE)
        self.update_btn.clicked.connect(self.check_for_updates)
        self.header_layout.addWidget(self.title_label, 1)
        self.header_layout.addWidget(self.update_btn, 0)
        self.vbox.addLayout(self.header_layout)

        self.input_hlayout = QHBoxLayout()
        self.input_hlayout.setSpacing(10)

        self.url_input = LineEdit(self)
        self.url_input.setPlaceholderText("Paste URL here or ask AI (e.g. 'download python 3.12 installer')...")
        self.url_input.setMinimumHeight(40)
        self.url_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.url_input.setClearButtonEnabled(True)
        self.url_input.returnPressed.connect(self.add_download)

        self.add_btn = PrimaryPushButton('Download', self, FIF.DOWNLOAD)
        self.add_btn.setMinimumHeight(40)
        self.add_btn.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.add_btn.clicked.connect(self.add_download)

        self.paste_file_btn = PushButton('Paste from File', self, FIF.DOCUMENT)
        self.paste_file_btn.setMinimumHeight(40)
        self.paste_file_btn.setToolTip("Import and batch download multiple links from a text file")
        self.paste_file_btn.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.paste_file_btn.clicked.connect(self.import_urls_from_file)

        self.input_hlayout.addWidget(self.url_input, 1)
        self.input_hlayout.addWidget(self.add_btn, 0)
        self.input_hlayout.addWidget(self.paste_file_btn, 0)

        self.vbox.addLayout(self.input_hlayout)

        # Action Toolbar (Batch controls and task count)
        self.toolbar_layout = QHBoxLayout()
        self.toolbar_layout.setContentsMargins(0, 0, 0, 0)
        self.toolbar_layout.setSpacing(8)

        self.counter_label = CaptionLabel("0 tasks in queue", self)
        self.counter_label.setWordWrap(True)
        self.btn_pause_all = TransparentPushButton("Pause All", self, FIF.PAUSE)
        self.btn_pause_all.clicked.connect(self.pause_all_downloads)
        self.btn_resume_all = TransparentPushButton("Resume All", self, FIF.PLAY)
        self.btn_resume_all.clicked.connect(self.resume_all_downloads)
        self.btn_clear_completed = TransparentPushButton("Clear Completed", self, FIF.DELETE)
        self.btn_clear_completed.clicked.connect(self.clear_completed_downloads)

        self.toolbar_layout.addWidget(self.counter_label)
        self.toolbar_layout.addStretch()
        self.toolbar_layout.addWidget(self.btn_pause_all)
        self.toolbar_layout.addWidget(self.btn_resume_all)
        self.toolbar_layout.addWidget(self.btn_clear_completed)
        self.vbox.addLayout(self.toolbar_layout)

        self.scroll_area = ScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("QScrollArea {background: transparent; border: none;}")

        self.scroll_widget = QWidget()
        self.scroll_widget.setStyleSheet("QWidget {background: transparent;}")
        self.scroll_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        self.scroll_layout.setAlignment(Qt.AlignTop)
        self.scroll_layout.setSpacing(10)

        # Empty State Card
        self.empty_card = CardWidget(self.scroll_widget)
        empty_layout = QVBoxLayout(self.empty_card)
        empty_layout.setContentsMargins(24, 36, 24, 36)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_layout.setSpacing(10)

        empty_icon = IconWidget(FIF.DOWNLOAD, self.empty_card)
        empty_icon.setFixedSize(48, 48)
        empty_title = StrongBodyLabel("No Active Downloads", self.empty_card)
        empty_title.setWordWrap(True)
        empty_subtitle = CaptionLabel("Paste a download link or type a prompt above to start downloading with AI routing.", self.empty_card)
        empty_subtitle.setWordWrap(True)
        empty_subtitle.setAlignment(Qt.AlignCenter)

        empty_layout.addWidget(empty_icon, 0, Qt.AlignCenter)
        empty_layout.addWidget(empty_title, 0, Qt.AlignCenter)
        empty_layout.addWidget(empty_subtitle, 0, Qt.AlignCenter)
        self.scroll_layout.addWidget(self.empty_card)

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
        try:
            tasks = get_all_tasks()

            for task in tasks:
                status = getattr(task, "status", "pending") or "pending"
                category = getattr(task, "category", "General") or "General"
                threat = getattr(task, "threat_level", "safe") or "safe"

                # Incomplete tasks loaded from previous sessions should be paused, not auto-started
                if status in ("pending", "downloading"):
                    status = "paused"

                card = DownloadCard(
                    task.url,
                    task.filename,
                    task.save_path,
                    task_id=task.id,
                    status=status,
                    category=category,
                    threat_level=threat,
                    auto_start=False,
                    parent=self
                )

                card.taskFinished.connect(self.on_card_finished)
                self.scroll_layout.addWidget(card)

        except Exception:
            pass

        self._update_ui_counters()

    def _update_ui_counters(self):
        count = 0
        active_count = 0
        for i in range(self.scroll_layout.count()):
            w = self.scroll_layout.itemAt(i).widget()
            if isinstance(w, DownloadCard):
                count += 1
                if getattr(w, 'state', '') in ('downloading', 'pending'):
                    active_count += 1

        if count == 0:
            self.empty_card.show()
            self.counter_label.setText("0 tasks in queue")
        else:
            self.empty_card.hide()
            status_text = f"{count} task{'s' if count != 1 else ''} in queue"
            if active_count > 0:
                status_text += f" ({active_count} active)"
            self.counter_label.setText(status_text)

    def pause_all_downloads(self):
        for i in range(self.scroll_layout.count()):
            w = self.scroll_layout.itemAt(i).widget()
            if isinstance(w, DownloadCard) and getattr(w, 'state', '') == "downloading":
                w.toggle_pause()
        self._update_ui_counters()

    def resume_all_downloads(self):
        for i in range(self.scroll_layout.count()):
            w = self.scroll_layout.itemAt(i).widget()
            if isinstance(w, DownloadCard) and getattr(w, 'state', '') in ("paused", "error", "queued"):
                w.toggle_pause()
        self._update_ui_counters()

    def clear_completed_downloads(self):
        to_remove = []
        for i in range(self.scroll_layout.count()):
            w = self.scroll_layout.itemAt(i).widget()
            if isinstance(w, DownloadCard) and getattr(w, 'state', '') == "completed":
                to_remove.append(w)

        for card in to_remove:
            self.scroll_layout.removeWidget(card)
            card.deleteLater()

        self._update_ui_counters()
        if to_remove:
            InfoBar.success("Cleaned", f"Cleared {len(to_remove)} completed download tasks.", parent=self.window())

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
        text = self.url_input.text().strip()

        if not text:
            return

        # Check if input is a natural language prompt instead of direct URL
        if not text.startswith(("http://", "https://", "ftp://")):
            self.handle_natural_language_prompt(text)
            return

        self.create_download_card(
            text,
            auto_start=True,
            status="pending",
            insert_top=True
        )

        self.url_input.clear()

    def handle_natural_language_prompt(self, prompt_text):
        InfoBar.info("AI Assistant", "Resolving download request...", parent=self.window(), duration=2000)
        self.nl_worker = NLPromptWorker(prompt_text, parent=self)
        self.nl_worker.resolved.connect(lambda res: self._on_nl_resolved(res, prompt_text))
        self.nl_worker.start()

    def _on_nl_resolved(self, result, original_prompt):
        software_name = result.get("software_name", original_prompt)
        url = result.get("official_url") or result.get("direct_link_hint")

        if url and url.startswith("http"):
            w = MessageBox(
                'AI Download Assistant',
                f'Found official source for "{software_name}":\n\n{url}\n\nStart download now?',
                self.window()
            )
            w.yesButton.setText('Download')
            w.cancelButton.setText('Cancel')

            if w.exec():
                self.url_input.setText(url)
                self.add_download()
        else:
            InfoBar.warning(
                "AI Assistant",
                f"Could not resolve a direct download link for '{original_prompt}'. Please provide a direct URL.",
                parent=self.window(),
                duration=4000
            )

    def create_download_card(self, url, auto_start=True, status="pending", insert_top=True):
        raw_name = url.split('/')[-1].split('?')[0] if '/' in url else 'unknown_file.bin'
        if not raw_name or raw_name == url:
            raw_name = "download_file.bin"

        # Apply Smart Routing & Category Discovery
        base_downloads = get_setting("default_download_dir", os.path.join(os.path.expanduser("~"), "Downloads"))
        save_dir, category = SmartRouter.route_download(url, raw_name, default_dir=base_downloads)
        os.makedirs(save_dir, exist_ok=True)

        task_id = create_task(url, raw_name, save_dir, category=category)

        card = DownloadCard(
            url,
            raw_name,
            save_dir,
            task_id=task_id,
            status=status,
            category=category,
            auto_start=auto_start,
            parent=self
        )

        card.taskFinished.connect(self.on_card_finished)

        if insert_top:
            self.scroll_layout.insertWidget(0, card)
        else:
            self.scroll_layout.addWidget(card)

        self._update_ui_counters()
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

    def check_for_updates(self):
        self.update_btn.setEnabled(False)
        self.update_btn.setText('Checking...')

        channel = get_setting("update_channel", "stable")
        self.update_worker = UpdateCheckWorker(current_version=__version__, channel=channel, parent=self)
        self.update_worker.finished_check.connect(self._on_update_checked)
        self.update_worker.failed_check.connect(self._on_update_failed)
        self.update_worker.start()

    def _on_update_checked(self, info: dict):
        self.update_btn.setEnabled(True)
        self.update_btn.setText('Check for Updates')

        if info.get("has_update"):
            dialog = UpdateDialog(info, parent=self.window())
            dialog.exec_()
        else:
            InfoBar.success(
                'Up to Date',
                f'{APP_NAME} is up to date (v{__version__}).',
                parent=self.window(),
                duration=3000
            )

    def _on_update_failed(self, error_msg: str):
        self.update_btn.setEnabled(True)
        self.update_btn.setText('Check for Updates')
        InfoBar.warning(
            'Update Check Failed',
            f'Unable to check for updates: {error_msg}',
            parent=self.window(),
            duration=4000
        )