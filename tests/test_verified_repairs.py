import time
import zipfile
import zlib
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest
from PyQt5.QtCore import QThread
from PyQt5.QtWidgets import QApplication

from app.controllers.downloader import DownloadWorker
from app.services.password_finder import PasswordFinder
from app.services.update_installer import UpdateInstaller
from app.services.updater import UpdateDownloadWorker


def test_invalid_reconnect_is_never_written(tmp_path, monkeypatch):
    worker = DownloadWorker(1, 'https://example.test/file', str(tmp_path))
    worker.file_path = str(tmp_path / 'file')
    worker.part_path = worker.file_path + '.part'
    worker._meta_path = worker.part_path + '.ngmeta'
    worker.total_size = 10
    worker._etag = '"stable"'

    class Response:
        status_code = 206
        headers = {'Content-Range': 'bytes 0-6/10'}
        def close(self):
            pass
        def iter_content(self, size):
            yield b'WRONG!!'

    class Initial(Response):
        status_code = 200
        def iter_content(self, size):
            yield b'abc'
            raise OSError('connection dropped')

    monkeypatch.setattr(worker, '_open_stream', lambda *a: Response())
    monkeypatch.setattr('app.controllers.downloader.time.sleep', lambda *a: None)
    errors = []
    worker.error.connect(errors.append)
    worker._download_single(None, Initial(), range_supported=True)
    assert Path(worker.part_path).read_bytes() == b'abc'
    assert not Path(worker.file_path).exists()
    assert errors


def test_zip_inflate_error_tries_next_password(tmp_path, monkeypatch):
    tried = []
    class Archive:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def infolist(self):
            return []
        def extractall(self, path, pwd):
            tried.append(pwd)
            if pwd != b'correct':
                raise zlib.error('invalid compressed data')
    monkeypatch.setattr(zipfile, 'ZipFile', lambda *a: Archive())
    monkeypatch.setattr(zipfile, 'is_zipfile', lambda *a: True)
    (tmp_path / 'file.zip').touch()
    result = PasswordFinder.extract_archive(str(tmp_path / 'file.zip'), ['wrong', 'correct'])
    assert result['success']
    assert tried[-1] == b'correct'


@pytest.mark.parametrize('failure', ['invalid', 'swap'])
def test_install_failure_preserves_old_install(tmp_path, monkeypatch, failure):
    install = tmp_path / 'installed'
    install.mkdir()
    (install / 'NeuroGet.exe').write_bytes(b'old')
    payload = tmp_path / 'payload.zip'
    if failure == 'invalid':
        payload.write_bytes(b'invalid zip')
    else:
        with zipfile.ZipFile(payload, 'w') as archive:
            archive.writestr('NeuroGet.exe', b'new')
        import os
        replace = os.replace
        def fail_swap(src, dst):
            if Path(src).name.startswith('.neuroget-stage-'):
                raise PermissionError('locked')
            return replace(src, dst)
        monkeypatch.setattr(os, 'replace', fail_swap)
    with pytest.raises(Exception):
        UpdateInstaller.install_payload(str(payload), str(install))
    assert (install / 'NeuroGet.exe').read_bytes() == b'old'


def test_update_without_checksum_never_downloads(monkeypatch):
    request = Mock()
    monkeypatch.setattr('app.services.updater.requests.get', request)
    worker = UpdateDownloadWorker('https://example.test/setup.exe', '1.2')
    failures = []
    worker.download_failed.connect(failures.append)
    worker.run()
    assert failures
    request.assert_not_called()


def test_bad_update_checksum_preserves_existing_installer(tmp_path, monkeypatch):
    target = tmp_path / 'setup.exe'
    target.write_bytes(b'previous verified installer')
    response = Mock(status_code=200, headers={'content-length': '3'})
    response.iter_content.return_value = [b'bad']
    monkeypatch.setattr('app.services.updater.requests.get', lambda *a, **k: response)
    monkeypatch.setattr(UpdateInstaller, 'get_target_installer_path', lambda *a: str(target))
    monkeypatch.setattr(UpdateInstaller, 'cleanup_old_updates', lambda **k: None)
    worker = UpdateDownloadWorker('https://example.test/setup.exe', '1.2', expected_hash='0' * 64)
    failures = []
    completed = []
    worker.download_failed.connect(failures.append)
    worker.download_finished.connect(completed.append)
    worker.run()
    assert failures and not completed
    assert target.read_bytes() == b'previous verified installer'
    assert not Path(str(target) + '.download').exists()
    response.close.assert_called_once()


def test_cancel_cleanup_cannot_delete_another_workers_partial(tmp_path):
    first = DownloadWorker(1, 'https://example.test/file', str(tmp_path))
    second = DownloadWorker(2, 'https://example.test/file', str(tmp_path))
    first.part_path = second.part_path = str(tmp_path / 'file.part')
    Path(first.part_path).write_bytes(b'in progress')
    first._path_lock = first._try_lock_path(first.part_path)
    try:
        second.cleanup_incomplete_files()
        assert Path(first.part_path).read_bytes() == b'in progress'
    finally:
        first._release_path_lock()


def test_finalize_does_not_emit_native_thread_finished(tmp_path):
    gate = Event()
    finalized = Event()
    class Worker(DownloadWorker):
        def run(self):
            self._finalize()
            finalized.set()
            gate.wait(5)
    worker = Worker(1, 'https://example.test/file', str(tmp_path))
    worker.file_path = str(tmp_path / 'file')
    worker.part_path = worker.file_path + '.part'
    worker._meta_path = worker.part_path + '.ngmeta'
    Path(worker.part_path).write_bytes(b'abc')
    native = []
    worker.finished.connect(lambda: native.append(True))
    worker.start()
    try:
        assert finalized.wait(3)
        QApplication.processEvents()
        assert worker.isRunning()
        assert native == []
    finally:
        gate.set()
        worker.wait(3000)
    QApplication.processEvents()
    assert native == [True]


def test_close_is_deferred_until_worker_exits(monkeypatch):
    from main import MainWindow
    from PyQt5.QtGui import QCloseEvent
    gate = Event()
    class Worker(QThread):
        def run(self):
            gate.wait(5)
    worker = Worker()
    worker.start()
    window = Mock()
    window.findChildren.return_value = [worker]
    scheduled = Mock()
    monkeypatch.setattr('main.QTimer.singleShot', scheduled)
    event = QCloseEvent()
    try:
        MainWindow.closeEvent(window, event)
        assert not event.isAccepted()
        assert worker.isRunning()
        scheduled.assert_called_once_with(100, window.close)
    finally:
        gate.set()
        worker.wait(3000)
