import sys
import os
import zipfile
import shutil
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication, QVBoxLayout, QHBoxLayout, QWidget
from qfluentwidgets import (SubtitleLabel, ProgressBar, PrimaryPushButton, 
                            BodyLabel, InfoBar, setTheme, Theme, ImageLabel)

class InstallWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool)
    
    def run(self):
        try:
            base_path = sys._MEIPASS if hasattr(sys, '_MEIPASS') else os.path.dirname(os.path.abspath(__file__))
            payload_path = os.path.join(base_path, 'payload.zip')
            
            if not os.path.exists(payload_path):
                self.progress.emit(0, "Payload not found! Run from compiled setup.")
                self.finished.emit(False)
                return

            install_dir = os.path.expandvars(r"%LOCALAPPDATA%\Programs\NeuroGet")
            if os.path.exists(install_dir):
                shutil.rmtree(install_dir, ignore_errors=True)
            os.makedirs(install_dir, exist_ok=True)
            
            self.progress.emit(10, "Extracting files...")
            
            with zipfile.ZipFile(payload_path, 'r') as zip_ref:
                total_files = len(zip_ref.infolist())
                for i, file_info in enumerate(zip_ref.infolist()):
                    zip_ref.extract(file_info, install_dir)
                    pct = int(10 + (i / total_files) * 80)
                    if i % 10 == 0:  # Update text occasionally to prevent UI spam
                        self.progress.emit(pct, f"Extracting {file_info.filename[:40]}...")
                    else:
                        self.progress.emit(pct, "") # Just update bar
                    
            self.progress.emit(90, "Creating shortcuts...")
            
            # Create Shortcut using VBScript (No dependencies needed!)
            target_path = os.path.join(install_dir, 'NeuroGet.exe')
            desktop = os.path.expandvars(r"%USERPROFILE%\Desktop")
            shortcut_path = os.path.join(desktop, "NeuroGet.lnk")
            vbs_path = os.path.join(install_dir, "createshortcut.vbs")
            
            vbs_content = f'''
Set oWS = WScript.CreateObject("WScript.Shell")
sLinkFile = "{shortcut_path}"
Set oLink = oWS.CreateShortcut(sLinkFile)
oLink.TargetPath = "{target_path}"
oLink.WorkingDirectory = "{install_dir}"
oLink.IconLocation = "{target_path}"
oLink.Save
'''
            with open(vbs_path, "w") as f:
                f.write(vbs_content)
                
            os.system(f'cscript //Nologo "{vbs_path}"')
            if os.path.exists(vbs_path):
                os.remove(vbs_path)
            
            self.progress.emit(100, "Installation Complete!")
            self.finished.emit(True)
        except Exception as e:
            self.progress.emit(0, str(e))
            self.finished.emit(False)

class SetupWizard(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NeuroGet Installer")
        
        base_path = sys._MEIPASS if hasattr(sys, '_MEIPASS') else os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(base_path, "assets", "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        self.resize(550, 400)
        
        # Center
        desktop = QApplication.desktop().availableGeometry()
        self.move(desktop.width()//2 - self.width()//2, desktop.height()//2 - self.height()//2)
        self.setStyleSheet("QWidget#SetupWizard { background-color: #202020; }")
        self.setObjectName("SetupWizard")
        
        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(40, 40, 40, 40)
        self.vbox.setSpacing(20)
        
        # Logo
        logo_path = os.path.join(base_path, "assets", "logo_transparent.png")
        if os.path.exists(logo_path):
            self.logo = ImageLabel(logo_path, self)
            self.logo.setFixedSize(120, 120)
            self.logo.scaledToWidth(120)
            self.logo_layout = QHBoxLayout()
            self.logo_layout.addWidget(self.logo, 0, Qt.AlignCenter)
            self.vbox.addLayout(self.logo_layout)
        
        self.title = SubtitleLabel("Install NeuroGet", self)
        self.title.setAlignment(Qt.AlignCenter)
        self.vbox.addWidget(self.title)
        
        self.status = BodyLabel("Ready to install NeuroGet AI Download Manager.", self)
        self.status.setAlignment(Qt.AlignCenter)
        self.vbox.addWidget(self.status)
        
        self.progress_bar = ProgressBar(self)
        self.progress_bar.setValue(0)
        self.vbox.addWidget(self.progress_bar)
        
        self.btn = PrimaryPushButton("Install", self)
        self.btn.clicked.connect(self.start_install)
        
        self.btn_layout = QHBoxLayout()
        self.btn_layout.addStretch(1)
        self.btn_layout.addWidget(self.btn)
        self.btn_layout.addStretch(1)
        self.vbox.addLayout(self.btn_layout)
        
        self.worker = None

    def start_install(self):
        if self.btn.text() == "Install":
            self.btn.setEnabled(False)
            self.btn.setText("Installing...")
            self.worker = InstallWorker()
            self.worker.progress.connect(self.update_progress)
            self.worker.finished.connect(self.install_finished)
            self.worker.start()
        elif self.btn.text() == "Launch NeuroGet":
            install_dir = os.path.expandvars(r"%LOCALAPPDATA%\Programs\NeuroGet")
            target_path = os.path.join(install_dir, 'NeuroGet', 'NeuroGet.exe')
            os.startfile(target_path)
            QApplication.quit()

    def update_progress(self, val, text):
        self.progress_bar.setValue(val)
        if text:
            self.status.setText(text)

    def install_finished(self, success):
        self.btn.setEnabled(True)
        if success:
            self.btn.setText("Launch NeuroGet")
        else:
            self.btn.setText("Install")
            InfoBar.error("Error", "Installation failed.", parent=self)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    setTheme(Theme.DARK)
    w = SetupWizard()
    w.show()
    sys.exit(app.exec_())
