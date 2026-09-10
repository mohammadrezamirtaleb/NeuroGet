import os
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget, QTextEdit,
    QScrollArea, QFrame, QLabel, QStackedWidget
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from qfluentwidgets import (
    TitleLabel, SubtitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel,
    SegmentedWidget, PrimaryPushButton, PushButton, LineEdit,
    TextEdit, InfoBar, InfoBarPosition, CardWidget, IconWidget
)
from qfluentwidgets import FluentIcon as FIF

from app.services.content_analyzer import ContentAnalyzer
from app.services.ai_client import AIClient


class SummaryWorker(QThread):
    finished_analysis = pyqtSignal(dict)

    def __init__(self, filepath):
        super().__init__()
        self.filepath = filepath

    def run(self):
        result = ContentAnalyzer.analyze_file(self.filepath)
        self.finished_analysis.emit(result)


class ChatWorker(QThread):
    response_ready = pyqtSignal(str)

    def __init__(self, document_text, query):
        super().__init__()
        self.document_text = document_text
        self.query = query

    def run(self):
        reply = AIClient.chat_with_document(self.document_text, self.query)
        self.response_ready.emit(reply)


class AISummaryDialog(QDialog):
    """Windows 11 Fluent modal providing AI Document/Media Summary,

    Interactive Mini-RAG Chat with file, and Metadata inspector.
    """

    def __init__(self, filepath, parent=None):
        super().__init__(parent)
        self.filepath = filepath
        self.filename = os.path.basename(filepath)
        self.analysis_data = {}
        self.document_text = ""

        self.setWindowTitle(f"NeuroGet AI - {self.filename}")
        self.resize(750, 580)
        self.setMinimumSize(650, 480)

        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(28, 24, 28, 24)
        self.vbox.setSpacing(16)

        # Header
        self.header = QHBoxLayout()
        self.icon_widget = IconWidget(FIF.ROBOT, self)
        self.icon_widget.setFixedSize(36, 36)
        
        self.title_vbox = QVBoxLayout()
        self.title_label = StrongBodyLabel(f"AI Intelligence: {self.filename}", self)
        self.sub_label = CaptionLabel("Instant summary, key topics, and interactive document Q&A", self)
        self.title_vbox.addWidget(self.title_label)
        self.title_vbox.addWidget(self.sub_label)

        self.header.addWidget(self.icon_widget)
        self.header.addLayout(self.title_vbox, 1)
        self.vbox.addLayout(self.header)

        # Segmented Tab Navigation
        self.pivot = SegmentedWidget(self)
        self.stacked_widget = QStackedWidget(self)

        self.tab_summary = self._create_summary_tab()
        self.tab_chat = self._create_chat_tab()
        self.tab_meta = self._create_meta_tab()

        self.stacked_widget.addWidget(self.tab_summary)
        self.stacked_widget.addWidget(self.tab_chat)
        self.stacked_widget.addWidget(self.tab_meta)

        self.pivot.addItem('summary', 'AI Summary', onClick=lambda: self.stacked_widget.setCurrentIndex(0))
        self.pivot.addItem('chat', 'Chat with File', onClick=lambda: self.stacked_widget.setCurrentIndex(1))
        self.pivot.addItem('meta', 'Structure & Metadata', onClick=lambda: self.stacked_widget.setCurrentIndex(2))
        self.pivot.setCurrentItem('summary')

        self.vbox.addWidget(self.pivot)
        self.vbox.addWidget(self.stacked_widget, 1)

        # Footer Actions
        self.footer = QHBoxLayout()
        self.status_label = CaptionLabel("Analyzing file content with AI...", self)
        self.close_btn = PushButton("Close", self)
        self.close_btn.clicked.connect(self.accept)

        self.footer.addWidget(self.status_label)
        self.footer.addStretch()
        self.footer.addWidget(self.close_btn)
        self.vbox.addLayout(self.footer)

        # Start asynchronous analysis
        self._start_analysis()

    def _create_summary_tab(self):
        w = QWidget(self)
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(0, 10, 0, 0)
        vbox.setSpacing(12)

        self.summary_card = CardWidget(w)
        card_layout = QVBoxLayout(self.summary_card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(10)

        # Stats bar
        self.stats_layout = QHBoxLayout()
        self.badge_words = CaptionLabel("Words: Analyzing...", self.summary_card)
        self.badge_time = CaptionLabel("Reading Time: Analyzing...", self.summary_card)
        self.stats_layout.addWidget(self.badge_words)
        self.stats_layout.addWidget(self.badge_time)
        self.stats_layout.addStretch()
        card_layout.addLayout(self.stats_layout)

        self.summary_text = TextEdit(self.summary_card)
        self.summary_text.setReadOnly(True)
        self.summary_text.setPlaceholderText("Generating AI insights...")
        card_layout.addWidget(self.summary_text)

        vbox.addWidget(self.summary_card, 1)
        return w

    def _create_chat_tab(self):
        w = QWidget(self)
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(0, 10, 0, 0)
        vbox.setSpacing(10)

        self.chat_history = TextEdit(w)
        self.chat_history.setReadOnly(True)
        self.chat_history.setPlaceholderText("Ask any question about this document and get instant answers...")
        vbox.addWidget(self.chat_history, 1)

        input_layout = QHBoxLayout()
        self.chat_input = LineEdit(w)
        self.chat_input.setPlaceholderText("e.g. What is the key conclusion? Summarize section 2...")
        self.chat_input.returnPressed.connect(self.send_chat_message)

        self.btn_send = PrimaryPushButton("Ask AI", w, FIF.SEND)
        self.btn_send.clicked.connect(self.send_chat_message)

        input_layout.addWidget(self.chat_input, 1)
        input_layout.addWidget(self.btn_send)
        vbox.addLayout(input_layout)

        return w

    def _create_meta_tab(self):
        w = QWidget(self)
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(0, 10, 0, 0)

        self.meta_text = TextEdit(w)
        self.meta_text.setReadOnly(True)
        vbox.addWidget(self.meta_text, 1)

        return w

    def _start_analysis(self):
        self.worker = SummaryWorker(self.filepath)
        self.worker.finished_analysis.connect(self._on_analysis_finished)
        self.worker.start()

    def _on_analysis_finished(self, data):
        self.analysis_data = data
        self.document_text = data.get("raw_text", "")
        self.status_label.setText("AI Analysis Ready")

        # Update Summary Tab
        words = data.get("word_count", 0)
        reading_time = data.get("reading_time_min", 1)
        self.badge_words.setText(f"Volume: ~{words} items/words")
        self.badge_time.setText(f"Reading Time: ~{reading_time} min")

        summary_content = data.get("summary", "No summary available.")
        self.summary_text.setMarkdown(summary_content)

        # Update Metadata Tab
        meta = data.get("metadata", {})
        meta_lines = [
            f"• File Name: {meta.get('filename', self.filename)}",
            f"• Full Path: {self.filepath}",
            f"• File Size: {meta.get('size_formatted', 'Unknown')}",
            f"• Extension: {meta.get('extension', '').upper()}",
        ]
        if "item_count" in meta:
            meta_lines.append(f"• Archive Item Count: {meta.get('item_count')}")
            meta_lines.append(f"• Uncompressed Size: {meta.get('uncompressed_size_formatted')}")
        if "line_count" in meta:
            meta_lines.append(f"• Total Lines: {meta.get('line_count')}")

        if "files" in meta:
            meta_lines.append("\n--- Inner Archive Tree ---")
            for f in meta.get("files", [])[:50]:
                meta_lines.append(f"  [+] {f}")

        self.meta_text.setPlainText("\n".join(meta_lines))

        # Seed Chat Tab with Welcome Message
        self.chat_history.setPlainText(
            f"NeuroGet AI Assistant is ready.\n"
            f"Indexed contents of '{self.filename}'. What would you like to know?\n"
            f"----------------------------------------------------------------------------\n"
        )

    def send_chat_message(self):
        query = self.chat_input.text().strip()
        if not query:
            return

        self.chat_input.clear()
        self.btn_send.setEnabled(False)
        self.btn_send.setText("Thinking...")

        current_history = self.chat_history.toPlainText()
        self.chat_history.setPlainText(f"{current_history}\nYou: {query}\nAI: Searching document...")

        self.chat_worker = ChatWorker(self.document_text or self.summary_text.toPlainText(), query)
        self.chat_worker.response_ready.connect(self._on_chat_response)
        self.chat_worker.start()

    def _on_chat_response(self, reply):
        self.btn_send.setEnabled(True)
        self.btn_send.setText("Ask AI")

        # Replace 'Searching document...' with final reply
        text = self.chat_history.toPlainText()
        if "AI: Searching document..." in text:
            text = text.replace("AI: Searching document...", f"AI: {reply}\n")
        else:
            text += f"\nAI: {reply}\n"
        self.chat_history.setPlainText(text)
