import os
import re
import urllib.parse

from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QApplication,
    QFileDialog,
    QSizePolicy
)

from PyQt5.QtCore import Qt, QUrl, QTimer, QThread, pyqtSignal

from qfluentwidgets import (
    LineEdit,
    SearchLineEdit,
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
    CardWidget,
    SimpleCardWidget,
    IconWidget,
    SegmentedWidget,
    PillPushButton
)

from qfluentwidgets import FluentIcon as FIF

from app.views.components.download_card import DownloadCard
from app.services.router import SmartRouter
from app.services.ai_client import AIClient
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

        self.current_filter = "all"
        self.search_query = ""

        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(28, 20, 28, 20)
        self.vbox.setSpacing(14)

        # 1. Header Section
        self._build_header()

        # 2. Hero Input Area
        self._build_input_area()

        # 3. Filter Tabs & Search / Batch Toolbar
        self._build_toolbar()

        # 4. Scrollable Download List
        self._build_scroll_area()

        self.batch_queue = []
        self.active_batch_card = None

        self.clipboard = QApplication.clipboard()
        self.last_clipboard_text = ""
        self.clipboard.dataChanged.connect(self.check_clipboard)

        self.check_clipboard(is_startup=True)
        self.load_history()

    def _build_header(self):
        self.header_layout = QHBoxLayout()
        self.header_layout.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)

        self.title_label = TitleLabel('Downloads', self)
        self.title_label.setWordWrap(True)

        self.sub_title = CaptionLabel(
            "Multi-threaded download acceleration with autonomous AI routing & threat defense",
            self
        )
        self.sub_title.setWordWrap(True)

        title_col.addWidget(self.title_label)
        title_col.addWidget(self.sub_title)
        self.header_layout.addLayout(title_col, 1)

        # Quick header action
        self.paste_file_btn = PushButton('Import Links File', self, FIF.DOCUMENT)
        self.paste_file_btn.setToolTip("Import and batch download multiple links from a text file")
        self.paste_file_btn.clicked.connect(self.import_urls_from_file)
        self.header_layout.addWidget(self.paste_file_btn, 0)

        self.vbox.addLayout(self.header_layout)

    def _build_input_area(self):
        self.input_card = CardWidget(self)
        input_card_layout = QHBoxLayout(self.input_card)
        input_card_layout.setContentsMargins(14, 10, 14, 10)
        input_card_layout.setSpacing(10)

        # Quick AI / Download Icon
        input_icon = IconWidget(FIF.ROBOT, self.input_card)
        input_icon.setFixedSize(22, 22)
        input_card_layout.addWidget(input_icon)

        self.url_input = LineEdit(self.input_card)
        self.url_input.setPlaceholderText("Paste URL (HTTP/HTTPS/FTP) or ask AI (e.g. 'download python 3.12 installer')...")
        self.url_input.setMinimumHeight(38)
        self.url_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.url_input.setClearButtonEnabled(True)
        self.url_input.returnPressed.connect(self.add_download)
        input_card_layout.addWidget(self.url_input, 1)

        # Paste Clipboard Quick Button
        self.btn_paste_clip = ToolButton(FIF.PASTE, self.input_card)
        self.btn_paste_clip.setToolTip("Paste from Clipboard")
        self.btn_paste_clip.clicked.connect(self._paste_from_clipboard)
        input_card_layout.addWidget(self.btn_paste_clip)

        # Main Download Button
        self.add_btn = PrimaryPushButton('Download', self.input_card, FIF.DOWNLOAD)
        self.add_btn.setMinimumHeight(38)
        self.add_btn.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.add_btn.clicked.connect(self.add_download)
        input_card_layout.addWidget(self.add_btn)

        self.vbox.addWidget(self.input_card)

    def _build_toolbar(self):
        # Row 1: Filter Segmented Widget & Search LineEdit
        top_filter_row = QHBoxLayout()
        top_filter_row.setSpacing(12)

        self.filter_pivot = SegmentedWidget(self)
        self.filter_pivot.addItem('all', 'All Tasks', onClick=lambda: self._set_filter('all'))
        self.filter_pivot.addItem('downloading', 'Downloading', onClick=lambda: self._set_filter('downloading'))
        self.filter_pivot.addItem('completed', 'Completed', onClick=lambda: self._set_filter('completed'))
        self.filter_pivot.addItem('paused', 'Paused / Queued', onClick=lambda: self._set_filter('paused'))
        self.filter_pivot.setCurrentItem('all')

        self.search_input = SearchLineEdit(self)
        self.search_input.setPlaceholderText("Search tasks by name or URL...")
        self.search_input.setMinimumWidth(140)
        self.search_input.setMaximumWidth(260)
        self.search_input.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_changed)

        top_filter_row.addWidget(self.filter_pivot, 1)
        top_filter_row.addWidget(self.search_input, 0)
        self.vbox.addLayout(top_filter_row)

        # Row 2: Queue Counter & Batch Controls
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

    def _build_scroll_area(self):
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

        # Modern Elevated Empty State Card
        self.empty_card = CardWidget(self.scroll_widget)
        self.empty_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        empty_layout = QVBoxLayout(self.empty_card)
        empty_layout.setContentsMargins(24, 36, 24, 36)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_layout.setSpacing(12)

        empty_icon_card = SimpleCardWidget(self.empty_card)
        empty_icon_card.setFixedSize(56, 56)
        empty_icon_layout = QVBoxLayout(empty_icon_card)
        empty_icon_layout.setContentsMargins(0, 0, 0, 0)
        empty_icon_layout.setAlignment(Qt.AlignCenter)

        empty_icon = IconWidget(FIF.DOWNLOAD, empty_icon_card)
        empty_icon.setFixedSize(32, 32)
        empty_icon_layout.addWidget(empty_icon, 0, Qt.AlignCenter)
        empty_layout.addWidget(empty_icon_card, 0, Qt.AlignCenter)

        empty_title = StrongBodyLabel("Ready for Downloads", self.empty_card)
        empty_title.setWordWrap(True)
        empty_layout.addWidget(empty_title, 0, Qt.AlignCenter)

        empty_subtitle = CaptionLabel(
            "Paste any download link above or type a natural language prompt for AI to find and route files automatically.",
            self.empty_card
        )
        empty_subtitle.setWordWrap(True)
        empty_subtitle.setAlignment(Qt.AlignCenter)
        empty_subtitle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        empty_layout.addWidget(empty_subtitle, 0, Qt.AlignCenter)

        # Quick Tips / Feature Highlights
        tips_layout = QHBoxLayout()
        tips_layout.setSpacing(8)
        tips_layout.setAlignment(Qt.AlignCenter)

        chip1 = CaptionLabel("32 Parallel Segments", self.empty_card)
        chip2 = CaptionLabel("AI Semantic Auto-Routing", self.empty_card)
        chip3 = CaptionLabel("Real-Time Threat Inspection", self.empty_card)
        for c in (chip1, chip2, chip3):
            c.setStyleSheet("""
                CaptionLabel {
                    color: #888888;
                    background-color: rgba(255, 255, 255, 0.05);
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    border-radius: 4px;
                    padding: 2px 8px;
                    font-size: 11px;
                }
            """)
            tips_layout.addWidget(c)

        empty_layout.addLayout(tips_layout)
        self.scroll_layout.addWidget(self.empty_card)

        self.scroll_area.setWidget(self.scroll_widget)
        self.vbox.addWidget(self.scroll_area, 1)

    def _paste_from_clipboard(self):
        mime = self.clipboard.mimeData()
        if mime.hasText():
            text = mime.text().strip()
            if text:
                self.url_input.setText(text)
                self.url_input.setFocus()

    def _set_filter(self, filter_name: str):
        self.current_filter = filter_name
        self._apply_card_filters()

    def _on_search_changed(self, text: str):
        self.search_query = text.strip().lower()
        self._apply_card_filters()

    def _apply_card_filters(self):
        visible_count = 0
        total_cards = 0

        for i in range(self.scroll_layout.count()):
            w = self.scroll_layout.itemAt(i).widget()
            if isinstance(w, DownloadCard):
                total_cards += 1
                state = getattr(w, 'state', '').lower()
                filename = getattr(w, 'filename', '').lower()
                url = getattr(w, 'url', '').lower()

                # 1. State filter match
                match_state = True
                if self.current_filter == "downloading":
                    match_state = state in ("downloading", "pending")
                elif self.current_filter == "completed":
                    match_state = state == "completed"
                elif self.current_filter == "paused":
                    match_state = state in ("paused", "queued", "error")

                # 2. Search query match
                match_search = True
                if self.search_query:
                    match_search = self.search_query in filename or self.search_query in url

                if match_state and match_search:
                    w.show()
                    visible_count += 1
                else:
                    w.hide()

        if total_cards == 0:
            self.empty_card.show()
        else:
            self.empty_card.hide()

    def load_history(self):
        try:
            tasks = get_all_tasks()

            for task in tasks:
                status = getattr(task, "status", "pending") or "pending"
                category = getattr(task, "category", "General") or "General"
                threat = getattr(task, "threat_level", "safe") or "safe"

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
        completed_count = 0
        for i in range(self.scroll_layout.count()):
            w = self.scroll_layout.itemAt(i).widget()
            if isinstance(w, DownloadCard):
                count += 1
                st = getattr(w, 'state', '')
                if st in ('downloading', 'pending'):
                    active_count += 1
                elif st == 'completed':
                    completed_count += 1

        if count == 0:
            self.empty_card.show()
            self.counter_label.setText("0 tasks in queue")
        else:
            self.empty_card.hide()
            status_text = f"{count} task{'s' if count != 1 else ''} in queue"
            details = []
            if active_count > 0:
                details.append(f"{active_count} active")
            if completed_count > 0:
                details.append(f"{completed_count} completed")
            if details:
                status_text += f" ({', '.join(details)})"
            self.counter_label.setText(status_text)

        self._apply_card_filters()

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