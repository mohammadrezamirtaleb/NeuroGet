import os
import subprocess
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget,
    QStackedWidget, QApplication
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QTextCursor
from qfluentwidgets import (
    SubtitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel,
    SegmentedWidget, PrimaryPushButton, PushButton, TransparentPushButton,
    PillPushButton, LineEdit, TextEdit, InfoBar, InfoBarPosition,
    CardWidget, SimpleCardWidget, IconWidget, IndeterminateProgressRing,
    isDarkTheme, FluentIcon as FIF
)

from app.services.content_analyzer import ContentAnalyzer
from app.services.ai_client import AIClient


class SummaryWorker(QThread):
    finished_analysis = pyqtSignal(dict)

    def __init__(self, filepath, parent=None):
        super().__init__(parent)
        self.filepath = filepath

    def run(self):
        result = ContentAnalyzer.analyze_file(self.filepath)
        self.finished_analysis.emit(result)


class ChatWorker(QThread):
    response_ready = pyqtSignal(str)

    def __init__(self, document_text, query, parent=None):
        super().__init__(parent)
        self.document_text = document_text
        self.query = query

    def run(self):
        reply = AIClient.chat_with_document(self.document_text, self.query)
        self.response_ready.emit(reply)


class AISummaryDialog(QDialog):
    """Windows 11 Fluent modal providing AI Document/Media Summary,

    Interactive Mini-RAG Chat with file, and Metadata inspector.
    Designed according to Fluent Design System and UI/UX Pro Max standards.
    """

    def __init__(self, filepath, parent=None):
        super().__init__(parent)
        self.filepath = filepath
        self.filename = os.path.basename(filepath)
        self.analysis_data = {}
        self.document_text = ""
        self.worker = None
        self.chat_worker = None

        self.setWindowTitle(f"NeuroGet AI - {self.filename}")
        self.resize(800, 600)
        self.setMinimumSize(620, 460)

        # Apply Fluent-compliant theme background
        self._apply_theme_style()

        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(24, 18, 24, 18)
        self.vbox.setSpacing(14)

        # 1. Header Section
        self._build_header()

        # 2. Segmented Tab Navigation
        self.pivot = SegmentedWidget(self)
        self.stacked_widget = QStackedWidget(self)

        self.tab_summary = self._create_summary_tab()
        self.tab_chat = self._create_chat_tab()
        self.tab_meta = self._create_meta_tab()

        self.stacked_widget.addWidget(self.tab_summary)
        self.stacked_widget.addWidget(self.tab_chat)
        self.stacked_widget.addWidget(self.tab_meta)

        self.pivot.addItem('summary', 'AI Summary', onClick=lambda: self.stacked_widget.setCurrentIndex(0), icon=FIF.DOCUMENT)
        self.pivot.addItem('chat', 'Chat with File', onClick=lambda: self.stacked_widget.setCurrentIndex(1), icon=FIF.CHAT)
        self.pivot.addItem('meta', 'Structure & Metadata', onClick=lambda: self.stacked_widget.setCurrentIndex(2), icon=FIF.INFO)
        self.pivot.setCurrentItem('summary')

        self.vbox.addWidget(self.pivot)
        self.vbox.addWidget(self.stacked_widget, 1)

        # 3. Footer Section
        self._build_footer()

        # Start asynchronous file analysis
        self._start_analysis()

    def _apply_theme_style(self):
        dark = isDarkTheme()
        bg_color = "rgb(32, 32, 32)" if dark else "rgb(243, 243, 243)"
        self.setStyleSheet(f"""
            AISummaryDialog {{
                background-color: {bg_color};
            }}
            QScrollArea {{
                border: none;
                background-color: transparent;
            }}
        """)

    def _build_header(self):
        self.header = QHBoxLayout()
        self.header.setSpacing(14)

        # Glowing Fluent Icon Container
        self.icon_card = SimpleCardWidget(self)
        self.icon_card.setFixedSize(44, 44)
        icon_layout = QVBoxLayout(self.icon_card)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setAlignment(Qt.AlignCenter)
        self.icon_widget = IconWidget(FIF.ROBOT, self.icon_card)
        self.icon_widget.setFixedSize(24, 24)
        icon_layout.addWidget(self.icon_widget)

        self.title_vbox = QVBoxLayout()
        self.title_vbox.setSpacing(2)
        self.title_label = SubtitleLabel(f"AI Document Intelligence: {self.filename}", self)
        self.title_label.setWordWrap(True)
        self.sub_label = CaptionLabel("Instant semantic summaries, key topic extraction, and interactive document Q&A", self)
        self.sub_label.setWordWrap(True)
        self.title_vbox.addWidget(self.title_label)
        self.title_vbox.addWidget(self.sub_label)

        # Top-Right File Format Badge
        ext = os.path.splitext(self.filename)[1].replace(".", "").upper() or "FILE"
        self.badge_card = SimpleCardWidget(self)
        badge_layout = QHBoxLayout(self.badge_card)
        badge_layout.setContentsMargins(12, 6, 12, 6)
        badge_layout.setSpacing(6)
        self.badge_icon = IconWidget(FIF.TILES, self.badge_card)
        self.badge_icon.setFixedSize(14, 14)
        self.badge_text = CaptionLabel(f"{ext} Format", self.badge_card)
        badge_layout.addWidget(self.badge_icon)
        badge_layout.addWidget(self.badge_text)

        self.header.addWidget(self.icon_card)
        self.header.addLayout(self.title_vbox, 1)
        self.header.addWidget(self.badge_card)
        self.vbox.addLayout(self.header)

    def _create_summary_tab(self):
        w = QWidget(self)
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(0, 10, 0, 0)
        vbox.setSpacing(12)

        # 1. Bento Stat Cards Grid
        self.stats_row = QHBoxLayout()
        self.stats_row.setSpacing(12)

        # Card 1: Volume
        self.card_vol = SimpleCardWidget(w)
        lay1 = QHBoxLayout(self.card_vol)
        lay1.setContentsMargins(14, 10, 14, 10)
        lay1.setSpacing(10)
        ic1 = IconWidget(FIF.DOCUMENT, self.card_vol)
        ic1.setFixedSize(20, 20)
        col1 = QVBoxLayout()
        col1.setSpacing(1)
        self.badge_words_val = StrongBodyLabel("Analyzing...", self.card_vol)
        lbl1 = CaptionLabel("Content Volume", self.card_vol)
        col1.addWidget(self.badge_words_val)
        col1.addWidget(lbl1)
        lay1.addWidget(ic1)
        lay1.addLayout(col1)

        # Card 2: Read Time
        self.card_time = SimpleCardWidget(w)
        lay2 = QHBoxLayout(self.card_time)
        lay2.setContentsMargins(14, 10, 14, 10)
        lay2.setSpacing(10)
        ic2 = IconWidget(FIF.SPEED_HIGH, self.card_time)
        ic2.setFixedSize(20, 20)
        col2 = QVBoxLayout()
        col2.setSpacing(1)
        self.badge_time_val = StrongBodyLabel("Estimating...", self.card_time)
        lbl2 = CaptionLabel("Estimated Read", self.card_time)
        col2.addWidget(self.badge_time_val)
        col2.addWidget(lbl2)
        lay2.addWidget(ic2)
        lay2.addLayout(col2)

        # Card 3: AI Engine Status
        self.card_status = SimpleCardWidget(w)
        lay3 = QHBoxLayout(self.card_status)
        lay3.setContentsMargins(14, 10, 14, 10)
        lay3.setSpacing(10)
        ic3 = IconWidget(FIF.ACCEPT, self.card_status)
        ic3.setFixedSize(20, 20)
        col3 = QVBoxLayout()
        col3.setSpacing(1)
        self.badge_ai_val = StrongBodyLabel("Neural Engine", self.card_status)
        lbl3 = CaptionLabel("Processing Ready", self.card_status)
        col3.addWidget(self.badge_ai_val)
        col3.addWidget(lbl3)
        lay3.addWidget(ic3)
        lay3.addLayout(col3)

        self.stats_row.addWidget(self.card_vol)
        self.stats_row.addWidget(self.card_time)
        self.stats_row.addWidget(self.card_status)
        vbox.addLayout(self.stats_row)

        # 2. Executive Summary Main Card
        self.summary_card = CardWidget(w)
        card_layout = QVBoxLayout(self.summary_card)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setSpacing(10)

        # Summary Header inside Card
        sum_header = QHBoxLayout()
        sum_title = StrongBodyLabel("Executive Summary & Key Insights", self.summary_card)
        self.btn_copy_summary = TransparentPushButton("Copy Summary", self.summary_card, FIF.COPY)
        self.btn_copy_summary.clicked.connect(self._copy_summary_to_clipboard)

        sum_header.addWidget(sum_title)
        sum_header.addStretch()
        sum_header.addWidget(self.btn_copy_summary)
        card_layout.addLayout(sum_header)

        # Loading Progress Indicator
        self.loading_container = QWidget(self.summary_card)
        load_layout = QVBoxLayout(self.loading_container)
        load_layout.setAlignment(Qt.AlignCenter)
        load_layout.setSpacing(12)
        self.loading_ring = IndeterminateProgressRing(self.loading_container)
        self.loading_ring.setFixedSize(36, 36)
        self.loading_label = CaptionLabel("Analyzing file structure and synthesizing insights with AI...", self.loading_container)
        load_layout.addWidget(self.loading_ring, 0, Qt.AlignCenter)
        load_layout.addWidget(self.loading_label, 0, Qt.AlignCenter)
        card_layout.addWidget(self.loading_container)

        # Summary Text Box (Transparent, Markdown styled)
        self.summary_text = TextEdit(self.summary_card)
        self.summary_text.setReadOnly(True)
        self.summary_text.setPlaceholderText("Generating AI insights...")
        self.summary_text.setStyleSheet("""
            TextEdit, QTextEdit {
                border: none;
                background-color: transparent;
                font-family: 'Segoe UI', system-ui, sans-serif;
                font-size: 13px;
                line-height: 1.6;
            }
        """)
        self.summary_text.hide()
        card_layout.addWidget(self.summary_text, 1)

        vbox.addWidget(self.summary_card, 1)
        return w

    def _create_chat_tab(self):
        w = QWidget(self)
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(0, 10, 0, 0)
        vbox.setSpacing(10)

        # Chat Card
        chat_card = CardWidget(w)
        card_layout = QVBoxLayout(chat_card)
        card_layout.setContentsMargins(18, 14, 18, 14)
        card_layout.setSpacing(10)

        chat_header = QHBoxLayout()
        chat_title = StrongBodyLabel("Interactive File Chat (Mini-RAG)", chat_card)
        chat_desc = CaptionLabel("Ask questions grounded strictly in this document's content", chat_card)
        chat_desc.setWordWrap(True)
        chat_header.addWidget(chat_title)
        chat_header.addWidget(chat_desc)
        chat_header.addStretch()

        self.btn_clear_chat = TransparentPushButton("Clear Chat", chat_card, FIF.DELETE)
        self.btn_clear_chat.clicked.connect(self._reset_chat_history)
        chat_header.addWidget(self.btn_clear_chat)
        card_layout.addLayout(chat_header)

        # Chat History Box
        self.chat_history = TextEdit(chat_card)
        self.chat_history.setReadOnly(True)
        self.chat_history.setStyleSheet("""
            TextEdit, QTextEdit {
                border: none;
                background-color: transparent;
                font-family: 'Segoe UI', system-ui, sans-serif;
                font-size: 13px;
                line-height: 1.5;
            }
        """)
        card_layout.addWidget(self.chat_history, 1)

        # Quick Suggestion Chips
        chips_layout = QHBoxLayout()
        chips_layout.setSpacing(8)
        chip_label = CaptionLabel("Suggestions:", chat_card)
        chips_layout.addWidget(chip_label)

        self.chip1 = PillPushButton("💡 Summarize main points", chat_card)
        self.chip1.clicked.connect(lambda: self._apply_prompt_chip("Summarize the main points of this document."))
        self.chip2 = PillPushButton("💡 Key takeaways & conclusions", chat_card)
        self.chip2.clicked.connect(lambda: self._apply_prompt_chip("What are the key takeaways and conclusions?"))
        self.chip3 = PillPushButton("💡 Extract action items & numbers", chat_card)
        self.chip3.clicked.connect(lambda: self._apply_prompt_chip("Extract all action items, dates, and important metrics."))

        chips_layout.addWidget(self.chip1)
        chips_layout.addWidget(self.chip2)
        chips_layout.addWidget(self.chip3)
        chips_layout.addStretch()
        card_layout.addLayout(chips_layout)

        # Input Area
        input_layout = QHBoxLayout()
        input_layout.setSpacing(8)

        self.chat_input = LineEdit(chat_card)
        self.chat_input.setPlaceholderText("Ask any question about this document (Press Enter to send)...")
        self.chat_input.setClearButtonEnabled(True)
        self.chat_input.returnPressed.connect(self.send_chat_message)

        self.btn_send = PrimaryPushButton("Ask AI", chat_card, FIF.SEND)
        self.btn_send.clicked.connect(self.send_chat_message)

        input_layout.addWidget(self.chat_input, 1)
        input_layout.addWidget(self.btn_send)
        card_layout.addLayout(input_layout)

        vbox.addWidget(chat_card, 1)
        return w

    def _create_meta_tab(self):
        w = QWidget(self)
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(0, 10, 0, 0)
        vbox.setSpacing(12)

        # Properties Card
        props_card = CardWidget(w)
        props_layout = QVBoxLayout(props_card)
        props_layout.setContentsMargins(18, 16, 18, 16)
        props_layout.setSpacing(12)

        props_header = QHBoxLayout()
        props_title = StrongBodyLabel("File Properties & Checksums", props_card)
        props_header.addWidget(props_title)
        props_header.addStretch()

        self.btn_copy_meta = TransparentPushButton("Copy Details", props_card, FIF.COPY)
        self.btn_copy_meta.clicked.connect(self._copy_meta_to_clipboard)
        self.btn_reveal_file = TransparentPushButton("Reveal in Explorer", props_card, FIF.FOLDER)
        self.btn_reveal_file.clicked.connect(self._reveal_in_explorer)

        props_header.addWidget(self.btn_copy_meta)
        props_header.addWidget(self.btn_reveal_file)
        props_layout.addLayout(props_header)

        # Properties Text Box
        self.meta_text = TextEdit(props_card)
        self.meta_text.setReadOnly(True)
        self.meta_text.setStyleSheet("""
            TextEdit, QTextEdit {
                border: none;
                background-color: transparent;
                font-family: 'Consolas', 'Segoe UI Mono', monospace;
                font-size: 12px;
                line-height: 1.6;
            }
        """)
        props_layout.addWidget(self.meta_text, 1)

        vbox.addWidget(props_card, 1)
        return w

    def _build_footer(self):
        self.footer = QHBoxLayout()
        self.footer.setContentsMargins(4, 0, 4, 0)
        self.footer.setSpacing(10)

        self.status_icon = IconWidget(FIF.ACCEPT, self)
        self.status_icon.setFixedSize(16, 16)
        self.status_label = CaptionLabel("Analyzing file content with AI...", self)
        self.status_label.setWordWrap(True)

        self.close_btn = PushButton("Close", self)
        self.close_btn.setFixedWidth(100)
        self.close_btn.clicked.connect(self.accept)

        self.footer.addWidget(self.status_icon)
        self.footer.addWidget(self.status_label)
        self.footer.addStretch()
        self.footer.addWidget(self.close_btn)
        self.vbox.addLayout(self.footer)

    def _start_analysis(self):
        self.worker = SummaryWorker(self.filepath, parent=self)
        self.worker.finished_analysis.connect(self._on_analysis_finished)
        self.worker.start()

    def _on_analysis_finished(self, data):
        self.analysis_data = data
        self.document_text = data.get("raw_text", "")
        self.status_label.setText("AI Analysis Ready • Offline Neural Engine")

        # Hide loading spinner and display summary text
        self.loading_container.hide()
        self.summary_text.show()

        # Update Summary Tab
        words = data.get("word_count", 0)
        reading_time = data.get("reading_time_min", 1)
        self.badge_words_val.setText(f"{words:,} items/words")
        self.badge_time_val.setText(f"~{reading_time} min read")
        self.badge_ai_val.setText("Neural Summary")

        summary_content = data.get("summary", "No summary available.")
        self.summary_text.setMarkdown(summary_content)

        # Update Metadata Tab
        meta = data.get("metadata", {})
        meta_lines = [
            f"• File Name:     {meta.get('filename', self.filename)}",
            f"• File Location: {self.filepath}",
            f"• File Size:     {meta.get('size_formatted', 'Unknown')}",
            f"• Extension:     {meta.get('extension', '').upper() or 'N/A'}",
        ]
        if "item_count" in meta:
            meta_lines.append(f"• Archive Items: {meta.get('item_count')}")
            meta_lines.append(f"• Uncompressed:  {meta.get('uncompressed_size_formatted')}")
        if "line_count" in meta:
            meta_lines.append(f"• Total Lines:   {meta.get('line_count')}")

        if "files" in meta:
            meta_lines.append("\n" + "=" * 50)
            meta_lines.append("INNER ARCHIVE STRUCTURE")
            meta_lines.append("=" * 50)
            for f in meta.get("files", [])[:60]:
                meta_lines.append(f"  [+] {f}")
            if len(meta.get("files", [])) > 60:
                meta_lines.append(f"  ... and {len(meta.get('files', [])) - 60} more files.")

        self.meta_text.setPlainText("\n".join(meta_lines))

        # Seed Chat Tab with Welcome Message
        self._reset_chat_history()

    def _reset_chat_history(self):
        dark = isDarkTheme()
        tag_bg = "rgba(0, 153, 255, 0.15)"
        text_color = "#ffffff" if dark else "#1f1f1f"
        desc_color = "#a0a0a0" if dark else "#606060"

        welcome_html = f"""
        <div style='color: {text_color}; font-family: Segoe UI, sans-serif; font-size: 13px;'>
            <div style='background: {tag_bg}; border-radius: 8px; padding: 10px 14px; margin-bottom: 12px;'>
                <b style='color: #0099ff;'>🤖 NeuroGet AI Assistant:</b><br/>
                <span style='color: {desc_color};'>I have indexed the contents of <b>{self.filename}</b>. Feel free to ask questions, request bulleted summaries, or query specific details from the document.</span>
            </div>
        </div>
        """
        self.chat_history.setHtml(welcome_html)

    def _apply_prompt_chip(self, prompt):
        self.chat_input.setText(prompt)
        self.send_chat_message()

    def send_chat_message(self):
        query = self.chat_input.text().strip()
        if not query:
            return

        if self.chat_worker is not None and self.chat_worker.isRunning():
            return

        self.chat_input.clear()
        self.chat_input.setEnabled(False)
        self.btn_send.setEnabled(False)
        self.btn_send.setText("Thinking...")

        # Append user message bubble and AI thinking bubble
        dark = isDarkTheme()
        user_bg = "rgba(0, 153, 255, 0.2)"
        ai_bg = "rgba(255, 255, 255, 0.05)" if dark else "rgba(0, 0, 0, 0.04)"
        text_color = "#ffffff" if dark else "#1f1f1f"

        current_html = self.chat_history.toHtml()
        new_bubbles = f"""
        <div style='margin-bottom: 10px; font-family: Segoe UI, sans-serif; color: {text_color};'>
            <div style='background: {user_bg}; border-radius: 8px; padding: 8px 12px; margin-bottom: 6px; text-align: left;'>
                <b style='color: #0099ff;'>👤 You:</b><br/>
                {query}
            </div>
            <div id='ai-thinking' style='background: {ai_bg}; border-radius: 8px; padding: 8px 12px; margin-bottom: 6px;'>
                <b style='color: #2bba68;'>🤖 AI:</b><br/>
                <i>Searching document and generating answer...</i>
            </div>
        </div>
        """
        self.chat_history.setHtml(current_html + new_bubbles)
        self.chat_history.moveCursor(QTextCursor.End)

        context_text = self.document_text or self.summary_text.toPlainText()
        self.chat_worker = ChatWorker(context_text, query, parent=self)
        self.chat_worker.response_ready.connect(lambda reply: self._on_chat_response(reply))
        self.chat_worker.start()

    def _on_chat_response(self, reply):
        self.chat_input.setEnabled(True)
        self.btn_send.setEnabled(True)
        self.btn_send.setText("Ask AI")
        self.chat_input.setFocus()

        # Replace thinking text with the generated response
        current_html = self.chat_history.toHtml()
        formatted_reply = reply.replace("\n", "<br/>")
        if "<i>Searching document and generating answer...</i>" in current_html:
            updated_html = current_html.replace(
                "<i>Searching document and generating answer...</i>",
                formatted_reply
            )
        else:
            dark = isDarkTheme()
            ai_bg = "rgba(255, 255, 255, 0.05)" if dark else "rgba(0, 0, 0, 0.04)"
            text_color = "#ffffff" if dark else "#1f1f1f"
            updated_html = current_html + f"""
            <div style='background: {ai_bg}; border-radius: 8px; padding: 8px 12px; margin-bottom: 6px; font-family: Segoe UI, sans-serif; color: {text_color};'>
                <b style='color: #2bba68;'>🤖 AI:</b><br/>
                {formatted_reply}
            </div>
            """
        self.chat_history.setHtml(updated_html)
        self.chat_history.moveCursor(QTextCursor.End)

    def _copy_summary_to_clipboard(self):
        text = self.summary_text.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            InfoBar.success("Copied", "Executive summary copied to clipboard.", parent=self, position=InfoBarPosition.TOP)

    def _copy_meta_to_clipboard(self):
        text = self.meta_text.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            InfoBar.success("Copied", "File metadata copied to clipboard.", parent=self, position=InfoBarPosition.TOP)

    def _reveal_in_explorer(self):
        if os.path.exists(self.filepath):
            norm_path = os.path.normpath(self.filepath)
            subprocess.Popen(f'explorer /select,"{norm_path}"')

    def closeEvent(self, event):
        """Cleanly terminate workers and disconnect signals when modal closes."""
        if self.worker is not None and self.worker.isRunning():
            try:
                self.worker.finished_analysis.disconnect()
            except Exception:
                pass
            self.worker.quit()
            self.worker.wait(100)

        if self.chat_worker is not None and self.chat_worker.isRunning():
            try:
                self.chat_worker.response_ready.disconnect()
            except Exception:
                pass
            self.chat_worker.quit()
            self.chat_worker.wait(100)

        super().closeEvent(event)
