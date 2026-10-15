import sys
import os
import zipfile
import shutil
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QStandardPaths
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication, QVBoxLayout, QHBoxLayout, QWidget
from qfluentwidgets import (SubtitleLabel, ProgressBar, PrimaryPushButton, 
                            BodyLabel, InfoBar, setTheme, Theme, ImageLabel, LineEdit)

from app.common.version import __version__, APP_NAME
from app.services.update_installer import UpdateInstaller

def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        candidate = os.path.join(sys._MEIPASS, relative_path)
        if os.path.exists(candidate):
            return candidate
    exe_candidate = os.path.join(os.path.dirname(sys.executable), relative_path)
    if os.path.exists(exe_candidate):
        return exe_candidate
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

class InstallWorker(QThread):
    progress = pyqtSignal(int, str)
    install_finished = pyqtSignal(bool)
    
    def run(self):
        try:
            payload_path = resource_path('payload.zip')
            
            if not os.path.exists(payload_path):
                self.progress.emit(0, "Payload not found! Run from compiled setup.")
                self.install_finished.emit(False)
                return

            import subprocess
            import time
            
            install_dir = os.path.expandvars(r"%LOCALAPPDATA%\Programs\NeuroGet")
            
            self.progress.emit(10, "Extracting files...")
            
            def _terminate_running():
                subprocess.run(
                    ['taskkill', '/F', '/IM', 'NeuroGet.exe'], check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                time.sleep(0.2)

            UpdateInstaller.install_payload(
                payload_path, install_dir,
                before_replace=_terminate_running)
                    
            self.progress.emit(85, "Creating shortcuts...")
            
            target_path = os.path.normpath(os.path.join(install_dir, 'NeuroGet.exe'))
            desktop = QStandardPaths.writableLocation(QStandardPaths.DesktopLocation)
            shortcut_path = os.path.normpath(os.path.join(desktop, "NeuroGet.lnk")) if desktop else ""
            vbs_path = os.path.join(install_dir, "createshortcut.vbs")
            
            vbs_content = f'''
Set oWS = WScript.CreateObject("WScript.Shell")

' 1. Desktop shortcut (resolves OneDrive-redirected and standard desktop automatically)
strDesktop = oWS.SpecialFolders("Desktop")
If strDesktop <> "" Then
    On Error Resume Next
    Set oLinkDesk = oWS.CreateShortcut(strDesktop & "\\NeuroGet.lnk")
    oLinkDesk.TargetPath = "{target_path}"
    oLinkDesk.WorkingDirectory = "{install_dir}"
    oLinkDesk.IconLocation = "{target_path}"
    oLinkDesk.Save
    On Error Goto 0
End If

' Explicit Python resolved desktop if different and valid
sExplicitDesktop = "{shortcut_path}"
If sExplicitDesktop <> "" And sExplicitDesktop <> strDesktop & "\\NeuroGet.lnk" Then
    On Error Resume Next
    Set oLinkExp = oWS.CreateShortcut(sExplicitDesktop)
    oLinkExp.TargetPath = "{target_path}"
    oLinkExp.WorkingDirectory = "{install_dir}"
    oLinkExp.IconLocation = "{target_path}"
    oLinkExp.Save
    On Error Goto 0
End If

' 2. Programs / Start Menu shortcut
strPrograms = oWS.SpecialFolders("Programs")
If strPrograms <> "" Then
    On Error Resume Next
    Set oLinkProg = oWS.CreateShortcut(strPrograms & "\\NeuroGet.lnk")
    oLinkProg.TargetPath = "{target_path}"
    oLinkProg.WorkingDirectory = "{install_dir}"
    oLinkProg.IconLocation = "{target_path}"
    oLinkProg.Save
    On Error Goto 0
End If
'''
            try:
                with open(vbs_path, "w", encoding="utf-8") as f:
                    f.write(vbs_content)
                subprocess.run(['cscript', '//Nologo', vbs_path], check=False, creationflags=subprocess.CREATE_NO_WINDOW)
                if os.path.exists(vbs_path):
                    os.remove(vbs_path)
            except Exception as shortcut_err:
                print(f"Warning: could not create shortcuts: {shortcut_err}")
                
            self.progress.emit(95, "Registering uninstaller...")
            try:
                import winreg
                key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\NeuroGet"
                key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
                winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, f"{APP_NAME} AI Download Manager")
                winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, __version__)
                winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, APP_NAME)
                winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, target_path)
                
                # Support standard, OneDrive, and Start Menu shortcut removal on uninstall
                uninstall_cmd = (
                    f'cmd.exe /c timeout /t 2 >nul & '
                    f'rmdir /s /q "{install_dir}" & '
                    f'del /q "%USERPROFILE%\\Desktop\\NeuroGet.lnk" 2>nul & '
                    f'del /q "%USERPROFILE%\\OneDrive\\Desktop\\NeuroGet.lnk" 2>nul & '
                    f'del /q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\NeuroGet.lnk" 2>nul & '
                    f'reg delete "HKCU\\{key_path}" /f'
                )
                winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, uninstall_cmd)
                winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
                winreg.CloseKey(key)
            except Exception as reg_err:
                print(f"Warning: could not register uninstaller: {reg_err}")
            
            self.progress.emit(100, "Installation Complete!")
            self.install_finished.emit(True)
        except Exception as e:
            self.progress.emit(0, str(e))
            self.install_finished.emit(False)

class SetupWizard(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NeuroGet Installer")
        
        icon_path = resource_path(os.path.join("assets", "icon.ico"))
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        self.resize(520, 420)
        self.setMinimumSize(460, 360)
        
        # Center
        desktop = QApplication.desktop().availableGeometry()
        self.move(max(0, desktop.width()//2 - self.width()//2), max(0, desktop.height()//2 - self.height()//2))
        self.setStyleSheet("QWidget#SetupWizard { background-color: #202020; }")
        self.setObjectName("SetupWizard")
        
        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(32, 24, 32, 24)
        self.vbox.setSpacing(16)
        
        # Logo
        logo_path = resource_path(os.path.join("assets", "logo_transparent.png"))
        if os.path.exists(logo_path):
            self.logo = ImageLabel(logo_path, self)
            self.logo.setFixedSize(100, 100)
            self.logo.scaledToWidth(100)
            self.logo_layout = QHBoxLayout()
            self.logo_layout.addWidget(self.logo, 0, Qt.AlignCenter)
            self.vbox.addLayout(self.logo_layout)
        
        self.title = SubtitleLabel("Install NeuroGet", self)
        self.title.setWordWrap(True)
        self.title.setAlignment(Qt.AlignCenter)
        self.vbox.addWidget(self.title)
        
        # Show Installation Path
        self.path_layout = QVBoxLayout()
        self.path_layout.setSpacing(5)
        self.path_label = BodyLabel("Installation Path:", self)
        self.path_layout.addWidget(self.path_label)
        
        self.path_input = LineEdit(self)
        self.path_input.setText(os.path.expandvars(r"%LOCALAPPDATA%\Programs\NeuroGet"))
        self.path_input.setReadOnly(True)
        self.path_layout.addWidget(self.path_input)
        self.vbox.addLayout(self.path_layout)
        
        self.status = BodyLabel("Ready to install NeuroGet AI Download Manager.", self)
        self.status.setWordWrap(True)
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
            self.worker = InstallWorker(parent=self)
            self.worker.progress.connect(self.update_progress)
            self.worker.install_finished.connect(self.install_finished)
            self.worker.start()
        elif self.btn.text() == "Launch NeuroGet":
            install_dir = os.path.expandvars(r"%LOCALAPPDATA%\Programs\NeuroGet")
            target_path = os.path.join(install_dir, 'NeuroGet.exe')
            try:
                os.startfile(target_path)
            except Exception:
                import subprocess
                subprocess.Popen([target_path], cwd=install_dir)
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
