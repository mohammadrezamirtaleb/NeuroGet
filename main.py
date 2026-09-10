import sys
import os
from PyQt5.QtCore import Qt, QSize, QTimer
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication

import qfluentwidgets
from qfluentwidgets import (NavigationInterface, NavigationItemPosition, FluentWindow,
                            SubtitleLabel, setTheme, Theme, NavigationAvatarWidget,
                            InfoBar, InfoBarPosition)
from qfluentwidgets import FluentIcon as FIF

# Add the project root to sys.path so 'app' module can be found
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.models.database import init_db, get_setting
from app.common.version import __version__, APP_NAME
from app.services.updater import UpdateCheckWorker
from app.views.components.update_dialog import UpdateDialog
from app.views.pages.downloads_page import DownloadsPage
from app.views.pages.smart_rules_page import SmartRulesPage
from app.views.pages.settings_page import SettingsPage
from app.views.splash_screen import NeuroSplashScreen

def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle('NeuroGet')
        self.setWindowIcon(QIcon(resource_path('assets/logo_transparent.png')))

        self.initWindow()

        # Create Pages
        self.downloads_interface = DownloadsPage(self)
        self.rules_interface = SmartRulesPage(self)
        self.settings_interface = SettingsPage(self)

        self.initNavigation()

        # Check for updates in the background after startup
        QTimer.singleShot(2500, self.check_updates_on_startup)

    def initNavigation(self):
        self.addSubInterface(self.downloads_interface, FIF.DOWNLOAD, 'Active Tasks')
        self.addSubInterface(self.rules_interface, FIF.APPLICATION, 'Smart Rules')
        
        self.navigationInterface.addSeparator()
        self.addSubInterface(self.settings_interface, FIF.SETTING, 'Settings', NavigationItemPosition.BOTTOM)
        
        self.navigationInterface.addItem(
            routeKey='ThemeToggle',
            icon=FIF.CONSTRACT,
            text='Toggle Theme',
            onClick=self.toggle_theme,
            position=NavigationItemPosition.BOTTOM
        )

    def initWindow(self):
        self.resize(1100, 750)
        self.setMinimumWidth(800)
        self.setMinimumHeight(600)
        
        # Center the window
        desktop = QApplication.desktop().availableGeometry()
        w, h = desktop.width(), desktop.height()
        self.move(w//2 - self.width()//2, h//2 - self.height()//2)

    def toggle_theme(self):
        if qfluentwidgets.theme() == Theme.DARK:
            setTheme(Theme.LIGHT)
        else:
            setTheme(Theme.DARK)

    def check_updates_on_startup(self):
        is_auto_check = get_setting("auto_check_updates", "true").lower() in ("true", "1", "yes")
        if not is_auto_check:
            return

        self._startup_updater = UpdateCheckWorker(current_version=__version__, parent=self)
        self._startup_updater.finished_check.connect(self._on_startup_update_detected)
        self._startup_updater.start()

    def _on_startup_update_detected(self, info: dict):
        if info.get("has_update"):
            latest_v = info.get("latest_version", "")
            InfoBar.info(
                f"Update Available (v{latest_v})",
                f"A new version of {APP_NAME} is available. Go to Settings to view changelog and update.",
                duration=10000,
                parent=self
            )

if __name__ == '__main__':
    # Initialize the local database
    init_db()

    # Enable high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

    app = QApplication(sys.argv)
    
    # Set default theme
    import qfluentwidgets
    setTheme(Theme.DARK)
    
    # Show Custom Splash Screen First
    splash = NeuroSplashScreen(resource_path('assets/logo.jpg'))
    
    # Main Window (hidden initially)
    w = MainWindow()
    
    def on_splash_finished():
        w.show()
        
    splash.finished.connect(on_splash_finished)
    splash.start()
    
    sys.exit(app.exec_())
