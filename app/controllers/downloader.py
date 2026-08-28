import os
import time
import requests
import urllib.parse
from PyQt5.QtCore import QThread, pyqtSignal

class DownloadWorker(QThread):
    metadata_ready = pyqtSignal(str, int)  # filename, total_size (bytes)
    progress_update = pyqtSignal(int, float, str)  # downloaded_bytes, speed (bytes/s), eta_str
    finished = pyqtSignal(str)  # final_file_path
    error = pyqtSignal(str)

    def __init__(self, task_id, url, save_dir):
        super().__init__()
        self.task_id = task_id
        self.url = url
        self.save_dir = save_dir
        self.is_paused = False
        self.is_cancelled = False
        
        self.filename = ""
        self.total_size = 0
        self.downloaded_size = 0
        self.file_path = ""

    def run(self):
        try:
            # 1. Fetch metadata (Headers)
            headers = {}
            if self.downloaded_size > 0:
                headers['Range'] = f"bytes={self.downloaded_size}-"
                
            response = requests.get(self.url, headers=headers, stream=True, timeout=15)
            response.raise_for_status()

            # Determine Total Size
            if response.status_code == 206: # Partial Content
                content_length = int(response.headers.get('content-length', 0))
                self.total_size = self.downloaded_size + content_length
            else:
                self.total_size = int(response.headers.get('content-length', 0))
                self.downloaded_size = 0 # Restart if server ignores Range
            
            # Determine Filename
            if not self.filename:
                cd = response.headers.get('content-disposition')
                if cd and 'filename=' in cd:
                    self.filename = cd.split('filename=')[1].strip('"\'')
                else:
                    self.filename = urllib.parse.unquote(self.url.split('/')[-1].split('?')[0])
                    if not self.filename:
                        self.filename = "downloaded_file"
            
            self.file_path = os.path.join(self.save_dir, self.filename)
            
            self.metadata_ready.emit(self.filename, self.total_size)

            # 2. Start Downloading
            mode = 'ab' if self.downloaded_size > 0 else 'wb'
            start_time = time.time()
            bytes_since_start = 0
            
            with open(self.file_path, mode) as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if self.is_cancelled:
                        break
                    
                    while self.is_paused:
                        time.sleep(0.1)
                        if self.is_cancelled:
                            break
                    
                    if self.is_cancelled:
                        break

                    if chunk:
                        f.write(chunk)
                        self.downloaded_size += len(chunk)
                        bytes_since_start += len(chunk)
                        
                        # Calculate Speed and ETA
                        elapsed = time.time() - start_time
                        if elapsed > 0.5:  # Update UI every 500ms
                            speed = bytes_since_start / elapsed
                            
                            eta = "Unknown"
                            if speed > 0 and self.total_size > 0:
                                remaining_bytes = self.total_size - self.downloaded_size
                                eta_secs = int(remaining_bytes / speed)
                                mins, secs = divmod(eta_secs, 60)
                                hours, mins = divmod(mins, 60)
                                if hours > 0:
                                    eta = f"{hours}h {mins}m {secs}s"
                                else:
                                    eta = f"{mins}m {secs}s"
                            
                            self.progress_update.emit(self.downloaded_size, speed, eta)
                            
                            # Reset interval
                            start_time = time.time()
                            bytes_since_start = 0

            if self.is_cancelled:
                self.error.emit("Download cancelled.")
            else:
                self.finished.emit(self.file_path)

        except Exception as e:
            self.error.emit(str(e))

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False

    def cancel(self):
        self.is_cancelled = True
        self.is_paused = False # Break out of pause loop
