import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidgetItem,
    QHeaderView, QFileDialog, QDialog
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from qfluentwidgets import (
    TitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel,
    ComboBox, PrimaryPushButton, PushButton, ToolButton, TableWidget,
    InfoBar, InfoBarPosition, SwitchButton, MessageBox, LineEdit, CardWidget
)
from qfluentwidgets import FluentIcon as FIF

from app.services.ai_scanner import LocalAIDetector, ScannerWorker
from app.services.ai_client import AIClient
from app.services.router import SmartRouter
from app.models.database import (
    get_all_rules, create_rule, delete_rule, toggle_rule,
    get_setting, set_setting
)


class TestRouteWorker(QThread):
    finished_test = pyqtSignal(dict)

    def __init__(self, test_input):
        super().__init__()
        self.test_input = test_input

    def run(self):
        filename = os.path.basename(self.test_input) if "/" in self.test_input or "\\" in self.test_input else self.test_input
        url = self.test_input if self.test_input.startswith("http") else ""
        category = AIClient.classify_category(filename, url)
        dest_dir, matched_rule = SmartRouter.route_download(url, filename)
        self.finished_test.emit({
            "filename": filename,
            "category": category,
            "dest_dir": dest_dir,
            "matched_rule": matched_rule
        })


class AddRuleDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add New Smart Rule")
        self.resize(500, 380)

        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(24, 20, 24, 20)
        self.vbox.setSpacing(14)

        self.vbox.addWidget(StrongBodyLabel("Rule Name:", self))
        self.name_input = LineEdit(self)
        self.name_input.setPlaceholderText("e.g. University PDF Documents")
        self.vbox.addWidget(self.name_input)

        self.vbox.addWidget(StrongBodyLabel("Condition Type:", self))
        self.type_combo = ComboBox(self)
        self.type_combo.addItem("File Extension Match (.ext)", "ext")
        self.type_combo.addItem("Filename Contains Keyword", "contains")
        self.type_combo.addItem("AI Semantic Category", "ai_category")
        self.vbox.addWidget(self.type_combo)

        self.vbox.addWidget(StrongBodyLabel("Condition Value:", self))
        self.val_input = LineEdit(self)
        self.val_input.setPlaceholderText("e.g. .pdf, .docx OR keyword OR Education / Course")
        self.vbox.addWidget(self.val_input)

        self.vbox.addWidget(StrongBodyLabel("Destination Folder:", self))
        self.dest_layout = QHBoxLayout()
        self.dest_input = LineEdit(self)
        self.dest_input.setPlaceholderText("Select destination directory...")
        self.browse_btn = PushButton("Browse", self, FIF.FOLDER)
        self.browse_btn.clicked.connect(self._browse_dir)
        self.dest_layout.addWidget(self.dest_input, 1)
        self.dest_layout.addWidget(self.browse_btn)
        self.vbox.addLayout(self.dest_layout)

        self.btn_layout = QHBoxLayout()
        self.save_btn = PrimaryPushButton("Save Rule", self, FIF.SAVE)
        self.save_btn.clicked.connect(self._validate_and_save)
        self.cancel_btn = PushButton("Cancel", self)
        self.cancel_btn.clicked.connect(self.reject)
        self.btn_layout.addStretch()
        self.btn_layout.addWidget(self.cancel_btn)
        self.btn_layout.addWidget(self.save_btn)
        self.vbox.addLayout(self.btn_layout)

    def _browse_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Destination Folder")
        if folder:
            self.dest_input.setText(folder)

    def _validate_and_save(self):
        name = self.name_input.text().strip() or "Custom Rule"
        cond_type = self.type_combo.currentData()
        cond_val = self.val_input.text().strip()
        dest = self.dest_input.text().strip()

        if not cond_val:
            InfoBar.warning("Missing Value", "Please specify a condition value.", parent=self)
            return

        if not dest:
            InfoBar.warning("Missing Folder", "Please choose a destination directory.", parent=self)
            return

        create_rule(name, cond_type, cond_val, dest, is_active=1)
        self.accept()


class SmartRulesPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("SmartRulesPage")
        self.scanner_thread = None

        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(40, 30, 40, 30)
        self.vbox.setSpacing(18)

        # Header with Master Switch
        self.header_layout = QHBoxLayout()
        self.title_label = TitleLabel('AI Smart Rules & Routing', self)

        self.enable_ai_switch = SwitchButton(parent=self)
        self.enable_ai_switch.setText('Enable AI Smart Routing')
        is_enabled = get_setting("enable_ai_smart_routing", "true").lower() in ("true", "1", "yes")
        self.enable_ai_switch.setChecked(is_enabled)
        self.enable_ai_switch.checkedChanged.connect(self._on_switch_changed)

        self.header_layout.addWidget(self.title_label)
        self.header_layout.addStretch()
        self.header_layout.addWidget(self.enable_ai_switch)
        self.vbox.addLayout(self.header_layout)

        self.desc_label = BodyLabel(
            'Automatically categorize and organize downloads using local or cloud AI models. '
            'Custom rules override default categories.', self
        )
        self.vbox.addWidget(self.desc_label)

        # AI Provider Selection Card
        self.provider_card = CardWidget(self)
        p_layout = QHBoxLayout(self.provider_card)
        p_layout.setContentsMargins(16, 12, 16, 12)
        p_layout.setSpacing(12)

        self.provider_label = StrongBodyLabel('Active AI Provider:', self.provider_card)
        self.model_combo = ComboBox(self.provider_card)
        self.model_combo.setMinimumWidth(320)
        self.model_combo.currentIndexChanged.connect(self._on_provider_changed)

        self.connect_btn = PushButton('Connect API Key', self.provider_card, FIF.LINK)
        self.connect_btn.clicked.connect(self.show_api_dialog)

        self.scan_btn = PrimaryPushButton('Scan Local AI', self.provider_card, FIF.SEARCH)
        self.scan_btn.clicked.connect(self.start_scan)

        p_layout.addWidget(self.provider_label)
        p_layout.addWidget(self.model_combo, 1)
        p_layout.addWidget(self.connect_btn)
        p_layout.addWidget(self.scan_btn)
        self.vbox.addWidget(self.provider_card)

        # Rules Table Section
        self.table_header_layout = QHBoxLayout()
        self.table_label = StrongBodyLabel('Active Auto-Routing Rules', self)
        
        self.add_rule_btn = PrimaryPushButton('Add Rule', self, FIF.ADD)
        self.add_rule_btn.clicked.connect(self.open_add_rule)

        self.del_rule_btn = PushButton('Delete Selected', self, FIF.DELETE)
        self.del_rule_btn.clicked.connect(self.delete_selected_rule)

        self.table_header_layout.addWidget(self.table_label)
        self.table_header_layout.addStretch()
        self.table_header_layout.addWidget(self.add_rule_btn)
        self.table_header_layout.addWidget(self.del_rule_btn)
        self.vbox.addLayout(self.table_header_layout)

        self.table = TableWidget(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(['Rule Name', 'Condition', 'Category / Value', 'Destination Folder'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.vbox.addWidget(self.table, 1)

        # Interactive Test Routing Section
        self.test_card = CardWidget(self)
        t_layout = QVBoxLayout(self.test_card)
        t_layout.setContentsMargins(16, 14, 16, 14)
        t_layout.setSpacing(10)

        t_layout.addWidget(StrongBodyLabel('Interactive Rule & AI Tester', self.test_card))

        test_input_layout = QHBoxLayout()
        self.test_input = LineEdit(self.test_card)
        self.test_input.setPlaceholderText("Enter a sample URL or filename (e.g. Machine_Learning_Book.pdf or Inception_1080p.mkv)...")
        self.test_input.returnPressed.connect(self.run_route_test)

        self.test_btn = PrimaryPushButton('Test Routing with AI', self.test_card, FIF.PLAY)
        self.test_btn.clicked.connect(self.run_route_test)

        test_input_layout.addWidget(self.test_input, 1)
        test_input_layout.addWidget(self.test_btn)
        t_layout.addLayout(test_input_layout)

        self.test_result_label = CaptionLabel("Result will appear here...", self.test_card)
        t_layout.addWidget(self.test_result_label)

        self.vbox.addWidget(self.test_card)

        # Cloud Providers List
        self.cloud_providers = [
            "OpenAI (GPT-4o-mini)",
            "Google (Gemini 1.5 Flash)",
            "Anthropic (Claude 3.5 Sonnet)",
            "OpenRouter (Universal)",
            "OpenCode Zen"
        ]

        self.load_rules_table()
        self.start_scan(silent=True)

    def _on_switch_changed(self, checked):
        set_setting("enable_ai_smart_routing", "true" if checked else "false")

    def _on_provider_changed(self):
        text = self.model_combo.currentText()
        if text:
            set_setting("ai_provider", text)

    def load_rules_table(self):
        rules = get_all_rules()
        self.table.setRowCount(len(rules))
        self.rule_objects = rules

        for row, rule in enumerate(rules):
            cond_type_str = "Extension (.ext)" if rule.condition_type == "ext" else ("Filename Contains" if rule.condition_type == "contains" else "AI Category")
            self.table.setItem(row, 0, QTableWidgetItem(getattr(rule, 'name', 'Custom Rule')))
            self.table.setItem(row, 1, QTableWidgetItem(cond_type_str))
            self.table.setItem(row, 2, QTableWidgetItem(rule.condition_value))
            self.table.setItem(row, 3, QTableWidgetItem(rule.destination_path))

    def open_add_rule(self):
        d = AddRuleDialog(self)
        if d.exec_():
            self.load_rules_table()
            InfoBar.success("Rule Added", "New routing rule saved successfully.", parent=self.window())

    def delete_selected_rule(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.rule_objects):
            InfoBar.warning("Select Rule", "Please select a rule from the table to delete.", parent=self.window())
            return

        rule = self.rule_objects[row]
        delete_rule(rule.id)
        self.load_rules_table()
        InfoBar.success("Rule Deleted", "Routing rule deleted.", parent=self.window())

    def show_api_dialog(self):
        provider = self.model_combo.currentText()
        if provider.startswith("Local:"):
            InfoBar.info('Local Model', 'Local models running on your machine do not require an API key.', parent=self.window())
            return

        saved_key = get_setting("ai_api_key", "")
        w = MessageBox(f'Configure {provider}', 'Enter your API Key for this AI provider:', self.window())
        api_input = LineEdit(w.widget)
        api_input.setText(saved_key)
        api_input.setPlaceholderText("sk-...")
        w.viewLayout.addWidget(api_input)

        if w.exec():
            api_key = api_input.text().strip()
            set_setting("ai_api_key", api_key)
            set_setting("ai_provider", provider)
            InfoBar.success('Saved', f'API Key configured for {provider}', parent=self.window())

    def start_scan(self, silent=False):
        if not silent:
            self.scan_btn.setEnabled(False)
            self.scan_btn.setText('Scanning...')
        self._silent_scan = silent

        self.scanner_thread = ScannerWorker()
        self.scanner_thread.finished_scan.connect(self.on_scan_finished)
        self.scanner_thread.start()

    def on_scan_finished(self, providers):
        self.model_combo.blockSignals(True)
        self.model_combo.clear()

        # Add detected local models
        if providers:
            for p in providers:
                for m in p.get("models", []):
                    if not m.startswith("("):
                        self.model_combo.addItem(f"Local: {p['provider']} - {m}")

        # Add Cloud Providers
        for p in self.cloud_providers:
            self.model_combo.addItem(p)

        saved = get_setting("ai_provider", "")
        if saved:
            idx = self.model_combo.findText(saved)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)

        self.model_combo.blockSignals(False)
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText('Scan Local AI')

        if not getattr(self, '_silent_scan', False):
            if providers:
                InfoBar.success(
                    'Scan Complete',
                    f"Found {len(providers)} local AI engine(s).",
                    parent=self.window(),
                    duration=3000
                )
            else:
                InfoBar.info(
                    'Scan Complete',
                    "No local AI server found. Cloud providers are available.",
                    parent=self.window(),
                    duration=3000
                )

    def run_route_test(self):
        text = self.test_input.text().strip()
        if not text:
            return

        self.test_btn.setEnabled(False)
        self.test_btn.setText("Evaluating...")

        self.test_worker = TestRouteWorker(text)
        self.test_worker.finished_test.connect(self._on_route_test_finished)
        self.test_worker.start()

    def _on_route_test_finished(self, res):
        self.test_btn.setEnabled(True)
        self.test_btn.setText("Test Routing with AI")

        self.test_result_label.setText(
            f"AI Detected Category: **{res['category']}** | "
            f"Matched Rule: **{res['matched_rule']}**\n"
            f"Target Folder: `{res['dest_dir']}`"
        )
