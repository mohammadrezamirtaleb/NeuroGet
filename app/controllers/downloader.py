import os
import time
import requests
import urllib3
import urllib.parse
from PyQt5.QtCore import QThread, pyqtSignal

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
        self.part_path = ""

    def run(self):
        try:
            headers = {}
            if self.downloaded_size > 0:
                headers['Range'] = f"bytes={self.downloaded_size}-"
                
            try:
                response = requests.get(self.url, headers=headers, stream=True, timeout=15)
            except requests.exceptions.SSLError:
                response = requests.get(self.url, headers=headers, stream=True, timeout=15, verify=False)
                
            response.raise_for_status()

            if response.status_code == 206: # Partial Content
                content_length = int(response.headers.get('content-length', 0))
                self.total_size = self.downloaded_size + content_length
            else:
                self.total_size = int(response.headers.get('content-length', 0))
                self.downloaded_size = 0 
            
            if not self.filename:
                cd = response.headers.get('content-disposition')
                if cd and 'filename=' in cd:
                    raw_name = cd.split('filename=')[1].split(';')[0].strip('"\'')
                else:
                    raw_name = urllib.parse.unquote(self.url.split('/')[-1].split('?')[0])
                
                # Prevent Path Traversal
                raw_name = os.path.basename(raw_name.replace('\\', '/'))
                self.filename = raw_name if raw_name else "downloaded_file"
            
            self.file_path = os.path.join(self.save_dir, self.filename)
            self.part_path = self.file_path + ".part"
            
            self.metadata_ready.emit(self.filename, self.total_size)

            mode = 'ab' if self.downloaded_size > 0 else 'wb'
            start_time = time.time()
            bytes_since_start = 0
            
            with open(self.part_path, mode) as f:
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
                        
                        elapsed = time.time() - start_time
                        if elapsed > 0.5:
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
                            start_time = time.time()
                            bytes_since_start = 0

            if self.is_cancelled:
                self.error.emit("Download cancelled.")
            elif self.total_size > 0 and self.downloaded_size < self.total_size:
                self.error.emit("Connection lost. Download incomplete.")
            else:
                if os.path.exists(self.file_path):
                    os.remove(self.file_path)
                os.rename(self.part_path, self.file_path)
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
