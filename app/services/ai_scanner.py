import os
import shutil
import subprocess
import requests
from PyQt5.QtCore import QThread, pyqtSignal

class LocalAIDetector:
    @staticmethod
    def detect_providers():
        providers = []

        # --- 1. Detect Ollama ---
        ollama_models = []
        ollama_online = False

        # 1a. Try Ollama HTTP API
        try:
            r = requests.get("http://localhost:11434/api/tags", timeout=2.5)
            if r.status_code == 200:
                raw_models = r.json().get("models", [])
                for m in raw_models:
                    name = m.get("name") or m.get("model")
                    if name and name not in ollama_models:
                        ollama_models.append(name)
                ollama_online = True
        except Exception:
            pass

        # 1b. Scan Local Disk Manifests for Installed Models
        disk_models = LocalAIDetector._scan_ollama_disk_manifests()
        for dm in disk_models:
            if dm not in ollama_models:
                ollama_models.append(dm)

        # 1c. Try CLI if models still not discovered
        if not ollama_models:
            cli_models = LocalAIDetector._scan_ollama_cli()
            for cm in cli_models:
                if cm not in ollama_models:
                    ollama_models.append(cm)

        ollama_path = shutil.which("ollama") or os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe")
        has_ollama = ollama_online or bool(ollama_models) or (ollama_path and os.path.exists(ollama_path))

        if ollama_models:
            status = "Online" if ollama_online else "Installed"
            providers.append({
                "provider": "Ollama",
                "status": status,
                "models": ollama_models
            })

        # --- 2. Detect LM Studio ---
        lm_models = []
        lm_online = False

        try:
            r = requests.get("http://localhost:1234/v1/models", timeout=2.0)
            if r.status_code == 200:
                raw_models = r.json().get("data", [])
                for m in raw_models:
                    model_id = m.get("id")
                    if model_id and model_id not in lm_models:
                        lm_models.append(model_id)
                lm_online = True
        except Exception:
            pass

        lm_disk_models = LocalAIDetector._scan_lm_studio_disk()
        for dm in lm_disk_models:
            if dm not in lm_models:
                lm_models.append(dm)

        lm_path1 = os.path.expandvars(r"%LOCALAPPDATA%\LM-Studio\LM Studio.exe")
        lm_path2 = os.path.expandvars(r"%LOCALAPPDATA%\Programs\lm-studio\LM Studio.exe")
        has_lm = lm_online or bool(lm_models) or os.path.exists(lm_path1) or os.path.exists(lm_path2)

        if has_lm:
            providers.append({
                "provider": "LM Studio",
                "status": "Online" if lm_online else "Installed",
                "models": lm_models if lm_models else ["Local Server Model"]
            })

        # --- 3. Detect GPT4All ---
        gpt_models = []
        gpt_online = False

        try:
            r = requests.get("http://localhost:4891/v1/models", timeout=2.0)
            if r.status_code == 200:
                raw_models = r.json().get("data", [])
                for m in raw_models:
                    model_id = m.get("id")
                    if model_id and model_id not in gpt_models:
                        gpt_models.append(model_id)
                gpt_online = True
        except Exception:
            pass

        gpt_path1 = os.path.expandvars(r"%LOCALAPPDATA%\nomic.ai\GPT4All\chat.exe")
        gpt_path2 = os.path.expandvars(r"%LOCALAPPDATA%\nomic.ai\GPT4All\bin\chat.exe")
        has_gpt = gpt_online or bool(gpt_models) or os.path.exists(gpt_path1) or os.path.exists(gpt_path2) or os.path.exists(r"C:\Program Files\GPT4All\bin\chat.exe")

        if has_gpt:
            providers.append({
                "provider": "GPT4All",
                "status": "Online" if gpt_online else "Installed",
                "models": gpt_models if gpt_models else ["Default Model"]
            })

        return providers

    @staticmethod
    def _scan_ollama_disk_manifests():
        models = []
        custom_path = os.environ.get('OLLAMA_MODELS')
        base_dirs = [custom_path] if custom_path else []
        base_dirs.extend([
            os.path.expanduser('~/.ollama/models/manifests'),
            os.path.expandvars(r'%USERPROFILE%\.ollama\models\manifests')
        ])

        for base in base_dirs:
            if base and os.path.exists(base):
                for root, dirs, files in os.walk(base):
                    for f in files:
                        rel = os.path.relpath(os.path.join(root, f), base)
                        parts = rel.replace('\\', '/').split('/')
                        # Typical structure: registry.ollama.ai/library/model_name/tag
                        if len(parts) >= 2:
                            model_name = parts[-2]
                            tag = parts[-1]
                            full_name = f"{model_name}:{tag}"
                            if full_name not in models:
                                models.append(full_name)
        return models

    @staticmethod
    def _scan_ollama_cli():
        models = []
        try:
            proc = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                timeout=2,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
            if proc.returncode == 0:
                lines = proc.stdout.strip().splitlines()
                for line in lines[1:]:  # Skip header line
                    parts = line.split()
                    if parts:
                        models.append(parts[0])
        except Exception:
            pass
        return models

    @staticmethod
    def _scan_lm_studio_disk():
        models = []
        base_dirs = [
            os.path.expanduser('~/.cache/lm-studio/models'),
            os.path.expandvars(r'%USERPROFILE%\.cache\lm-studio\models')
        ]
        for base in base_dirs:
            if os.path.exists(base):
                for root, dirs, files in os.walk(base):
                    for f in files:
                        if f.endswith('.gguf'):
                            rel = os.path.relpath(os.path.join(root, f), base)
                            model_id = rel.replace('\\', '/').rstrip('.gguf')
                            if model_id not in models:
                                models.append(model_id)
        return models


class ScannerWorker(QThread):
    finished_scan = pyqtSignal(list)

    def run(self):
        providers = LocalAIDetector.detect_providers()
        self.finished_scan.emit(providers)
