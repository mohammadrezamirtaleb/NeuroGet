"""Keep cancelled workers alive until their native thread has stopped."""
from PyQt5.QtCore import QTimer

retired_workers = set()


def retire_worker(worker):
    worker.setParent(None)
    retired_workers.add(worker)

    def reap():
        if worker.isRunning():
            QTimer.singleShot(50, reap)
            return
        retired_workers.discard(worker)
        worker.deleteLater()

    QTimer.singleShot(0, reap)
