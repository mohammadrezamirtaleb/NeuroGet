from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTableWidgetItem
from PyQt5.QtCore import Qt
from qfluentwidgets import (TitleLabel, StrongBodyLabel, BodyLabel, 
                            ComboBox, PrimaryPushButton, PushButton, TableWidget, 
                            InfoBar, InfoBarPosition, SwitchButton, MessageBox, LineEdit)
from qfluentwidgets import FluentIcon as FIF

from app.services.ai_scanner import LocalAIDetector, ScannerWorker

class SmartRulesPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("SmartRulesPage")
        self.scanner_thread = None
        
        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(40, 40, 40, 40)
        self.vbox.setSpacing(24)
        
        # Header with Master Switch
        self.header_layout = QHBoxLayout()
        self.title_label = TitleLabel('AI Smart Rules', self)
        
        self.enable_ai_switch = SwitchButton(parent=self)
        self.enable_ai_switch.setText('Enable AI Smart Routing')
        self.enable_ai_switch.setChecked(True)
        
        self.header_layout.addWidget(self.title_label)
        self.header_layout.addStretch()
        self.header_layout.addWidget(self.enable_ai_switch)
        self.vbox.addLayout(self.header_layout)
        
        self.desc_label = BodyLabel('Automatically categorize your downloads using local or cloud AI models. If disabled, files will go to the default folder.', self)
        self.vbox.addWidget(self.desc_label)
        
        # AI Provider Selection
        self.provider_layout = QHBoxLayout()
        self.provider_label = StrongBodyLabel('AI Provider:', self)
        self.model_combo = ComboBox(self)
        self.model_combo.setMinimumWidth(300)
        
        self.connect_btn = PushButton('Connect API', self, FIF.LINK)
        self.connect_btn.clicked.connect(self.show_api_dialog)
        
        self.scan_btn = PrimaryPushButton('Scan Local AI', self, FIF.SEARCH)
        self.scan_btn.clicked.connect(self.start_scan)
        
        self.provider_layout.addWidget(self.provider_label)
        self.provider_layout.addWidget(self.model_combo)
        self.provider_layout.addWidget(self.connect_btn)
        self.provider_layout.addWidget(self.scan_btn)
        self.provider_layout.addStretch(1)
        
        self.vbox.addLayout(self.provider_layout)
        
        # Rules Table
        self.table_label = StrongBodyLabel('Active Auto-Routing Rules', self)
        self.vbox.addWidget(self.table_label)
        
        self.table = TableWidget(self)
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(['Condition', 'Category', 'Destination Folder'])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.vbox.addWidget(self.table)
        
        # Cloud Providers List
        self.cloud_providers = [
            "OpenCode Zen (Claude, GPT, Gemini)",
            "Anthropic (Claude)",
            "GitHub Copilot",
            "OpenAI (GPT)",
            "Google (Gemini)",
            "OpenRouter",
            "Vercel AI Gateway"
        ]
        
        # Add mock rules and initial scan
        self.add_mock_rules()
        self.start_scan(silent=True)

    def show_api_dialog(self):
        provider = self.model_combo.currentText()
        if provider.startswith("Local:"):
            InfoBar.warning('Local Model', 'Local models do not require an API key.', parent=self.window())
            return
            
        w = MessageBox(f'Connect to {provider}', 'Please enter your API Key or connection string for this provider:', self.window())
        self.api_input = LineEdit(w.widget)
        self.api_input.setPlaceholderText("sk-...")
        w.viewLayout.addWidget(self.api_input)
        
        if w.exec():
            api_key = self.api_input.text()
            if api_key:
                InfoBar.success('Connected', f'Successfully connected to {provider}', parent=self.window())

    def start_scan(self, silent=False):
        # Disable button to prevent multiple clicks and freezing
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText('Scanning...')
        
        self.scanner_thread = ScannerWorker()
        # Lambda to pass the silent flag nicely, but QThread signals don't easily bind extra args without functools.partial.
        # We can store silent in the instance.
        self._silent_scan = silent
        self.scanner_thread.finished_scan.connect(self.on_scan_finished)
        self.scanner_thread.start()

    def on_scan_finished(self, providers):
        self.model_combo.clear()
        
        # 1. Add Cloud Providers
        for p in self.cloud_providers:
            self.model_combo.addItem(p)
            
        # 2. Add Local Providers
        if providers:
            for provider in providers:
                for model in provider["models"]:
                    self.model_combo.addItem(f"Local: {provider['provider']} - {model}")
                    
            if not getattr(self, '_silent_scan', False):
                InfoBar.success(
                    title='Scan Complete',
                    content=f"Found {len(providers)} local AI provider(s).",
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=3000,
                    parent=self
                )
        else:
            if not getattr(self, '_silent_scan', False):
                InfoBar.warning(
                    title='Local AI Not Found',
                    content="Could not detect Ollama/LMStudio. Only Cloud APIs are available.",
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=3000,
                    parent=self
                )
                
        # Re-enable button
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText('Scan Local AI')

    def add_mock_rules(self):
        self.table.setRowCount(3)
        self.table.setItem(0, 0, QTableWidgetItem("Contains 'tutorial'"))
        self.table.setItem(0, 1, QTableWidgetItem("Education"))
        self.table.setItem(0, 2, QTableWidgetItem("C:\\Downloads\\Education"))
        
        self.table.setItem(1, 0, QTableWidgetItem("Extension is .pdf"))
        self.table.setItem(1, 1, QTableWidgetItem("Documents"))
        self.table.setItem(1, 2, QTableWidgetItem("C:\\Downloads\\Docs"))
        
        self.table.setItem(2, 0, QTableWidgetItem("AI determines it is a Game"))
        self.table.setItem(2, 1, QTableWidgetItem("Games"))
        self.table.setItem(2, 2, QTableWidgetItem("D:\\Downloads\\Games"))
