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
from app.views.pages.about_page import AboutPage
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
        self.about_interface = AboutPage(self)

        self.initNavigation()

        # Check for updates in the background after startup
        QTimer.singleShot(2500, self.check_updates_on_startup)

    def initNavigation(self):
        self.addSubInterface(self.downloads_interface, FIF.DOWNLOAD, 'Active Tasks')
        self.addSubInterface(self.rules_interface, FIF.APPLICATION, 'Smart Rules')
        
        self.navigationInterface.addSeparator()
        self.addSubInterface(self.about_interface, FIF.INFO, 'About Us', NavigationItemPosition.BOTTOM)
        self.addSubInterface(self.settings_interface, FIF.SETTING, 'Settings', NavigationItemPosition.BOTTOM)
        
        self.navigationInterface.addItem(
            routeKey='CheckUpdates',
            icon=FIF.UPDATE,
            text='Check for Updates',
            onClick=self.manual_check_updates,
            position=NavigationItemPosition.BOTTOM
        )

        self.navigationInterface.addItem(
            routeKey='ThemeToggle',
            icon=FIF.CONSTRACT,
            text='Toggle Theme',
            onClick=self.toggle_theme,
            position=NavigationItemPosition.BOTTOM
        )

    def initWindow(self):
        self.resize(1024, 680)
        self.setMinimumWidth(720)
        self.setMinimumHeight(520)
        
        # Center the window
        desktop = QApplication.desktop().availableGeometry()
        w, h = desktop.width(), desktop.height()
        self.move(max(0, w//2 - self.width()//2), max(0, h//2 - self.height()//2))

    def toggle_theme(self):
        if qfluentwidgets.theme() == Theme.DARK:
            setTheme(Theme.LIGHT)
        else:
            setTheme(Theme.DARK)

    def manual_check_updates(self):
        channel = get_setting("update_channel", "stable")
        self._manual_updater = UpdateCheckWorker(current_version=__version__, channel=channel, parent=self)
        self._manual_updater.finished_check.connect(self._on_manual_update_checked)
        self._manual_updater.failed_check.connect(self._on_manual_update_failed)
        self._manual_updater.start()

    def _on_manual_update_checked(self, info: dict):
        if info.get("has_update"):
            dialog = UpdateDialog(info, parent=self)
            dialog.exec_()
        else:
            InfoBar.success(
                'Up to Date',
                f'{APP_NAME} is already running the latest version (v{__version__}).',
                parent=self,
                duration=3500
            )

    def _on_manual_update_failed(self, error_msg: str):
        InfoBar.warning(
            'Update Check Failed',
            f'Unable to check for updates: {error_msg}',
            parent=self,
            duration=4000
        )

    def check_updates_on_startup(self):
        is_auto_check = get_setting("auto_check_updates", "true").lower() in ("true", "1", "yes")
        if not is_auto_check:
            return

        channel = get_setting("update_channel", "stable")
        self._startup_updater = UpdateCheckWorker(current_version=__version__, channel=channel, parent=self)
        self._startup_updater.finished_check.connect(self._on_startup_update_detected)
        self._startup_updater.start()

    def _on_startup_update_detected(self, info: dict):
        if info.get("has_update"):
            dialog = UpdateDialog(info, parent=self)
            dialog.exec_()

    def closeEvent(self, event):
        """Gracefully shut down all background threads without blocking the main UI thread."""
        # Cancel all active download workers in DownloadsPage
        if hasattr(self, 'downloads_interface'):
            layout = self.downloads_interface.scroll_layout
            for i in range(layout.count()):
                widget = layout.itemAt(i).widget()
                if widget and hasattr(widget, 'db_timer'):
                    try:
                        widget.db_timer.stop()
                    except Exception:
                        pass
                if widget and hasattr(widget, 'worker') and widget.worker is not None:
                    try:
                        widget.worker.metadata_ready.disconnect()
                        widget.worker.progress_update.disconnect()
                        widget.worker.finished.disconnect()
                        widget.worker.error.disconnect()
                    except Exception:
                        pass
                    try:
                        widget.worker.cancel()
                        widget.worker.wait(50)
                    except Exception:
                        pass
                if widget and hasattr(widget, 'extract_worker') and widget.extract_worker is not None:
                    try:
                        widget.extract_worker.finished_extract.disconnect()
                    except Exception:
                        pass
                    try:
                        widget.extract_worker.cancel()
                        widget.extract_worker.wait(50)
                    except Exception:
                        pass

        # Stop update checkers if running
        for updater_attr in ('_startup_updater', '_manual_updater'):
            if hasattr(self, updater_attr):
                updater = getattr(self, updater_attr)
                if updater is not None and updater.isRunning():
                    try:
                        updater.finished_check.disconnect()
                        updater.failed_check.disconnect()
                    except Exception:
                        pass
                    try:
                        updater.quit()
                        updater.wait(50)
                    except Exception:
                        pass

        # Stop scanner thread if running
        if hasattr(self, 'rules_interface') and hasattr(self.rules_interface, 'scanner_thread'):
            scanner = self.rules_interface.scanner_thread
            if scanner is not None and scanner.isRunning():
                try:
                    scanner.finished_scan.disconnect()
                except Exception:
                    pass
                try:
                    scanner.quit()
                    scanner.wait(50)
                except Exception:
                    pass

        super().closeEvent(event)

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
    splash = NeuroSplashScreen(resource_path('assets/logo_transparent.png'))
    splash.start()
    app.processEvents()
    
    # Main Window (hidden initially)
    w = MainWindow()
    
    def on_splash_finished():
        w.show()
        
    splash.finished.connect(on_splash_finished)
    
    sys.exit(app.exec_())
