import os
import shutil
import requests
from PyQt5.QtCore import QThread, pyqtSignal

class LocalAIDetector:
    @staticmethod
    def detect_providers():
        providers = []
        
        # 1. Detect Ollama
        ollama_online = False
        try:
            r = requests.get("http://localhost:11434/api/tags", timeout=1)
            if r.status_code == 200:
                models = [m["name"] for m in r.json().get("models", [])]
                providers.append({
                    "provider": "Ollama",
                    "status": "Online",
                    "models": models if models else ["(No models downloaded)"]
                })
                ollama_online = True
        except requests.RequestException:
            pass
            
        if not ollama_online:
            ollama_path = shutil.which("ollama") or os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe")
            if ollama_path and os.path.exists(ollama_path):
                providers.append({
                    "provider": "Ollama (Offline)",
                    "status": "Offline",
                    "models": ["(Service Offline - Start Ollama to load models)"]
                })

        # 2. Detect LM Studio
        lm_online = False
        try:
            r = requests.get("http://localhost:1234/v1/models", timeout=1)
            if r.status_code == 200:
                models = [m["id"] for m in r.json().get("data", [])]
                providers.append({
                    "provider": "LM Studio",
                    "status": "Online",
                    "models": models if models else ["(No models loaded)"]
                })
                lm_online = True
        except requests.RequestException:
            pass

        if not lm_online:
            lm_path1 = os.path.expandvars(r"%LOCALAPPDATA%\LM-Studio\LM Studio.exe")
            lm_path2 = os.path.expandvars(r"%LOCALAPPDATA%\Programs\lm-studio\LM Studio.exe")
            if os.path.exists(lm_path1) or os.path.exists(lm_path2):
                providers.append({
                    "provider": "LM Studio (Offline)",
                    "status": "Offline",
                    "models": ["(Server Offline - Start LM Studio to load models)"]
                })

        # 3. Detect GPT4All
        gpt_online = False
        try:
            r = requests.get("http://localhost:4891/v1/models", timeout=1)
            if r.status_code == 200:
                models = [m["id"] for m in r.json().get("data", [])]
                providers.append({
                    "provider": "GPT4All",
                    "status": "Online",
                    "models": models if models else ["(No models loaded)"]
                })
                gpt_online = True
        except requests.RequestException:
            pass

        if not gpt_online:
            gpt_path1 = os.path.expandvars(r"%LOCALAPPDATA%\nomic.ai\GPT4All\chat.exe")
            gpt_path2 = os.path.expandvars(r"%LOCALAPPDATA%\nomic.ai\GPT4All\bin\chat.exe")
            if os.path.exists(gpt_path1) or os.path.exists(gpt_path2) or os.path.exists(r"C:\Program Files\GPT4All\bin\chat.exe"):
                providers.append({
                    "provider": "GPT4All (Offline)",
                    "status": "Offline",
                    "models": ["(Server Offline - Start GPT4All to load models)"]
                })
                
        return providers

class ScannerWorker(QThread):
    finished_scan = pyqtSignal(list)
    
    def run(self):
        providers = LocalAIDetector.detect_providers()
        self.finished_scan.emit(providers)
