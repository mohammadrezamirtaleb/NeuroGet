import os
import re
import json
import time
import requests
import urllib.parse
import logging
from app.models.database import get_setting

# Provider endpoints configuration
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_LMSTUDIO_HOST = "http://localhost:1234/v1"
DEFAULT_GPT4ALL_HOST = "http://localhost:4891/v1"
logger = logging.getLogger(__name__)

class AIClient:
    """Universal AI Client supporting Local (Ollama, LM Studio, GPT4All) and Cloud LLMs

    with automatic, instant heuristic fallbacks.
    """

    _offline_providers = {}  # {provider_key: offline_until_timestamp}
    _ollama_process_started = False

    @classmethod
    def get_configured_provider(cls):
        return get_setting("ai_provider", "Local: Ollama")

    @classmethod
    def get_api_key(cls):
        provider = cls.get_configured_provider()
        return get_setting(f"ai_api_key:{provider}", get_setting("ai_api_key", ""))

    @classmethod
    def get_model_name(cls):
        provider = cls.get_configured_provider()
        return get_setting(f"ai_model:{provider}", get_setting("ai_model", ""))

    @staticmethod
    def default_model(provider):
        name = provider.lower()
        if "anthropic" in name or "claude" in name:
            return "claude-sonnet-4-6"
        if "opencode" in name:
            return "glm-5.1"
        return ""

    @classmethod
    def call_llm(cls, prompt, system_prompt=None, max_tokens=500, timeout=6):
        """Sends prompt to the active AI provider. Returns response text or None on failure."""
        provider = cls.get_configured_provider()
        api_key = cls.get_api_key()
        model = cls.get_model_name()

        provider_key = provider.lower().strip()
        now = time.time()
        if provider_key in cls._offline_providers and now < cls._offline_providers[provider_key]:
            return None

        # Fast connect timeout tuple: (connect_timeout, read_timeout)
        fast_timeout = (1.5, timeout) if isinstance(timeout, (int, float)) else timeout

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Copilot subscriptions are not a generic API-key chat provider. Never
        # send their tokens to OpenAI or another unrelated service.
        if "copilot" in provider_key:
            logger.warning("Copilot is unsupported as an API-key provider; choose a supported provider.")
            return None

        if "anthropic" in provider_key or "claude" in provider_key or "opencode" in provider_key:
            if not api_key:
                return None
            try:
                selected_model = model or cls.default_model(provider)
                if "opencode" in provider_key:
                    result = cls._call_opencode(
                        prompt, system_prompt, selected_model, api_key, max_tokens, fast_timeout
                    )
                else:
                    result = cls._call_messages(
                        "https://api.anthropic.com/v1/messages", prompt, system_prompt,
                        selected_model, {"x-api-key": api_key}, max_tokens, fast_timeout
                    )
                cls._offline_providers.pop(provider_key, None)
                return result
            except Exception:
                cls._offline_providers[provider_key] = time.time() + 60.0
                return None

        # 1. Local: Ollama
        if "ollama" in provider.lower():
            # Determine model
            ollama_model = model
            if not ollama_model or "local:" in ollama_model.lower():
                if " - " in provider:
                    ollama_model = provider.split(" - ", 1)[1].strip()
                else:
                    from app.services.ai_scanner import LocalAIDetector
                    disk_models = LocalAIDetector._scan_ollama_disk_manifests()
                    ollama_model = disk_models[0] if disk_models else None

            if not ollama_model:
                # Do not send empty model to Ollama; mark offline cooldown and fallback immediately
                cls._offline_providers[provider_key] = time.time() + 60.0
                return None

            full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
            payload = {
                "model": ollama_model,
                "prompt": full_prompt,
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": max_tokens}
            }
            try:
                res = requests.post(f"{DEFAULT_OLLAMA_HOST}/api/generate", json=payload, timeout=fast_timeout)
                if res.status_code == 200:
                    cls._offline_providers.pop(provider_key, None)
                    return res.json().get("response", "").strip()
            except Exception:
                pass

            # Try to start ollama serve if not already started
            if not cls._ollama_process_started:
                cls._ollama_process_started = True
                try:
                    import shutil
                    import subprocess
                    ollama_bin = shutil.which("ollama") or os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe")
                    if ollama_bin and os.path.exists(ollama_bin):
                        subprocess.Popen(
                            [ollama_bin, "serve"],
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                        )
                        time.sleep(1.0)
                        res = requests.post(f"{DEFAULT_OLLAMA_HOST}/api/generate", json=payload, timeout=fast_timeout)
                        if res.status_code == 200:
                            cls._offline_providers.pop(provider_key, None)
                            return res.json().get("response", "").strip()
                except Exception:
                    pass

            cls._offline_providers[provider_key] = time.time() + 60.0
            return None

        # 2. Local: LM Studio or GPT4All (OpenAI-compatible)
        if "lm studio" in provider.lower() or "gpt4all" in provider.lower():
            host = DEFAULT_LMSTUDIO_HOST if "lm studio" in provider.lower() else DEFAULT_GPT4ALL_HOST
            try:
                payload = {
                    "messages": messages,
                    "temperature": 0.3,
                    "max_tokens": max_tokens
                }
                local_model = model or (provider.split(" - ", 1)[1].strip() if " - " in provider else "")
                if local_model:
                    payload["model"] = local_model
                res = requests.post(f"{host}/chat/completions", json=payload, timeout=fast_timeout)
                if res.status_code == 200:
                    data = res.json()
                    choices = data.get("choices", [])
                    if choices:
                        cls._offline_providers.pop(provider_key, None)
                        return choices[0].get("message", {}).get("content", "").strip()
            except Exception:
                cls._offline_providers[provider_key] = time.time() + 60.0

        # 3. Cloud: OpenAI / OpenRouter / Groq
        if any(p in provider.lower() for p in ["openai", "openrouter", "groq"]):
            if not api_key:
                return None
            try:
                endpoint = "https://api.openai.com/v1/chat/completions"
                if "openrouter" in provider.lower():
                    endpoint = "https://openrouter.ai/api/v1/chat/completions"
                elif "groq" in provider.lower():
                    endpoint = "https://api.groq.com/openai/v1/chat/completions"

                cloud_model = model or "gpt-4o-mini"
                payload = {
                    "model": cloud_model,
                    "messages": messages,
                    "temperature": 0.3,
                    "max_tokens": max_tokens
                }
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                res = requests.post(endpoint, json=payload, headers=headers, timeout=fast_timeout)
                if res.status_code == 200:
                    data = res.json()
                    choices = data.get("choices", [])
                    if choices:
                        cls._offline_providers.pop(provider_key, None)
                        return choices[0].get("message", {}).get("content", "").strip()
            except Exception:
                cls._offline_providers[provider_key] = time.time() + 60.0

        # 4. Cloud: Google Gemini
        if "gemini" in provider.lower() or "google" in provider.lower():
            if not api_key:
                return None
            try:
                gemini_model = model or "gemini-1.5-flash"
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={api_key}"
                full_text = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
                payload = {
                    "contents": [{"parts": [{"text": full_text}]}],
                    "generationConfig": {"temperature": 0.3, "maxOutputTokens": max_tokens}
                }
                res = requests.post(url, json=payload, timeout=fast_timeout)
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            cls._offline_providers.pop(provider_key, None)
                            return parts[0].get("text", "").strip()
            except Exception:
                cls._offline_providers[provider_key] = time.time() + 60.0

        return None

    @staticmethod
    def _call_messages(endpoint, prompt, system_prompt, model, auth, max_tokens, timeout):
        payload = {
            "model": model, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}]
        }
        if system_prompt:
            payload["system"] = system_prompt
        response = requests.post(endpoint, json=payload, timeout=timeout, headers={
            **auth, "anthropic-version": "2023-06-01", "Content-Type": "application/json"
        })
        response.raise_for_status()
        return "\n".join(
            part.get("text", "") for part in response.json().get("content", [])
            if part.get("type") == "text"
        ).strip() or None

    @classmethod
    def _call_opencode(cls, prompt, system_prompt, model, api_key, max_tokens, timeout):
        # https://opencode.ai/v2/docs/console/api/inference
        root = "https://opencode.ai/inference"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        lowered = model.lower()
        if lowered.startswith(("claude", "qwen")) and lowered != "qwen3.8-max":
            return cls._call_messages(
                root + "/anthropic/v1/messages", prompt, system_prompt,
                model, headers, max_tokens, timeout
            )
        if lowered.startswith("gemini"):
            response = requests.post(
                f"{root}/google/v1beta/models/{urllib.parse.quote(model, safe='')}:generateContent",
                headers=headers, timeout=timeout,
                json={"contents": [{"parts": [{"text": prompt}]}],
                      **({"systemInstruction": {"parts": [{"text": system_prompt}]}} if system_prompt else {}),
                      "generationConfig": {"maxOutputTokens": max_tokens}}
            )
            response.raise_for_status()
            candidates = response.json().get("candidates", [])
            return "\n".join(p.get("text", "") for p in candidates[0].get("content", {}).get("parts", [])).strip() if candidates else None
        if lowered.startswith(("gpt", "grok", "muse")):
            response = requests.post(
                root + "/openai/v1/responses", headers=headers, timeout=timeout,
                json={"model": model, "input": prompt, "max_output_tokens": max_tokens,
                      **({"instructions": system_prompt} if system_prompt else {})}
            )
            response.raise_for_status()
            return "\n".join(
                part.get("text", "") for item in response.json().get("output", [])
                for part in item.get("content", []) if part.get("type") == "output_text"
            ).strip() or None
        messages = ([{"role": "system", "content": system_prompt}] if system_prompt else [])
        messages.append({"role": "user", "content": prompt})
        response = requests.post(
            root + "/openai/v1/chat/completions", headers=headers, timeout=timeout,
            json={"model": model, "messages": messages, "max_tokens": max_tokens}
        )
        response.raise_for_status()
        choices = response.json().get("choices", [])
        return choices[0].get("message", {}).get("content", "").strip() if choices else None

    # --- Feature 1: AI Clean Renaming ---
    @classmethod
    def clean_filename(cls, raw_name, url=""):
        """Intelligently cleans messy download filenames using AI with regex heuristic fallback."""
        if not raw_name or raw_name == "download":
            if url:
                parsed = urllib.parse.urlparse(url)
                path_name = os.path.basename(parsed.path)
                if path_name:
                    raw_name = path_name
                else:
                    raw_name = "download_file.bin"
            else:
                return "download_file.bin"

        # Separate base and extension
        _, ext = os.path.splitext(raw_name)

        # 1. Try AI first if enabled
        prompt = (
            f"Given the messy downloaded filename '{raw_name}' from URL '{url}', "
            f"return ONLY the clean, properly capitalized, human-readable filename preserving the extension '{ext}'. "
            f"Remove website prefixes, brackets, ad words, and hash strings. Example: '[Soft98.ir]_python-3.12.0-amd64.exe' -> 'Python 3.12.0 (x64).exe'. "
            f"Output strictly the cleaned filename without any quotation marks or extra explanation."
        )
        ai_result = cls.call_llm(prompt, system_prompt="You are a file renaming assistant. Output ONLY the clean filename.", max_tokens=60, timeout=3)
        if ai_result:
            cleaned = ai_result.strip().strip('"\'`\n\r')
            # Validate extension preserved
            if cleaned and not cleaned.startswith(("{", "<", "error")):
                if not os.path.splitext(cleaned)[1] and ext:
                    cleaned += ext
                return cleaned

        # 2. Heuristic Regex Fallback
        return cls._heuristic_clean_name(raw_name)

    @classmethod
    def _heuristic_clean_name(cls, raw_name):
        name = urllib.parse.unquote(raw_name)
        
        # Strip URL parameters if stuck in filename
        if "?" in name:
            name = name.split("?")[0]

        # Remove common site prefixes like [Soft98.ir] or www.site.com_
        name = re.sub(r'^\[[a-zA-Z0-9._-]+\][\s_-]*', '', name)
        name = re.sub(r'^\([a-zA-Z0-9._-]+\)[\s_-]*', '', name)
        name = re.sub(r'^(?:www\.)?[a-zA-Z0-9-]+\.[a-zA-Z]{2,4}[_.\s-]+', '', name, flags=re.IGNORECASE)

        # Replace repeated underscores/dots with single space (except the extension)
        parts = os.path.splitext(name)
        base = parts[0]
        ext = parts[1]

        base = re.sub(r'[._]+', ' ', base).strip()
        # Clean multiple spaces
        base = re.sub(r'\s+', ' ', base)

        if not base:
            base = "downloaded_file"

        return f"{base}{ext}"

    # --- Feature 2: Semantic Categorization ---
    @classmethod
    def classify_category(cls, filename, url="", ext=""):
        """Classifies a download into a clean category using AI or heuristics."""
        if not ext and "." in filename:
            ext = os.path.splitext(filename)[1].lower()
        else:
            ext = ext.lower()

        prompt = (
            f"Classify this file into ONE of the following categories: "
            f"[Documents, Software, Media, Audio, Archives, Education / Course, Games, Images, General].\n"
            f"Filename: {filename}\nURL: {url}\nExtension: {ext}\n"
            f"Respond with ONLY the exact category name."
        )
        ai_category = cls.call_llm(prompt, system_prompt="You are a file classifier. Output ONLY the category name.", max_tokens=20, timeout=3)
        if ai_category:
            valid_cats = ["Documents", "Software", "Media", "Audio", "Archives", "Education / Course", "Games", "Images", "General"]
            for cat in valid_cats:
                if cat.lower() in ai_category.lower():
                    return cat

        # Heuristic fallback
        return cls._heuristic_category(filename, ext)

    @classmethod
    def _heuristic_category(cls, filename, ext):
        fn_lower = filename.lower()
        if ext in ['.pdf', '.docx', '.doc', '.txt', '.epub', '.pptx', '.xlsx', '.csv', '.rtf']:
            return "Documents"
        elif ext in ['.exe', '.msi', '.apk', '.dmg', '.iso', '.pkg', '.deb', '.rpm']:
            if any(k in fn_lower for k in ['game', 'repack', 'crack', 'fitgirl', 'dodi']):
                return "Games"
            return "Software"
        elif ext in ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm']:
            if any(k in fn_lower for k in ['tutorial', 'course', 'lecture', 'lesson', 'udemy']):
                return "Education / Course"
            return "Media"
        elif ext in ['.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a']:
            return "Audio"
        elif ext in ['.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz']:
            return "Archives"
        elif ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp', '.ico']:
            return "Images"
        return "General"

    # --- Feature 3: Text Summarization ---
    @classmethod
    def summarize_content(cls, text_content, filename=""):
        """Generates a structured 3-bullet summary, key tags, and reading stats."""
        # Trim text to max 4000 characters for LLM prompt safety
        sample = text_content[:4000]
        word_count = len(text_content.split())
        reading_time_min = max(1, round(word_count / 200))

        prompt = (
            f"Analyze the following document content from '{filename}' and provide:\n"
            f"1. A concise 3-bullet point summary of key takeaways.\n"
            f"2. Three relevant hashtag tags (e.g. #Python #AI #Tutorial).\n"
            f"3. Intended audience or primary domain.\n\n"
            f"Document Sample:\n\"\"\"\n{sample}\n\"\"\"\n\n"
            f"Format response cleanly with markdown."
        )

        ai_summary = cls.call_llm(
            prompt,
            system_prompt="You are an expert document summarizer. Be concise, structured, and insightful.",
            max_tokens=350,
            timeout=8
        )

        if ai_summary:
            return {
                "summary": ai_summary,
                "word_count": word_count,
                "reading_time_min": reading_time_min,
                "is_ai": True
            }

        # Extractive Heuristic Fallback
        sentences = [s.strip() for s in re.split(r'[.!?\n]+', sample) if len(s.strip()) > 30]
        top_bullets = sentences[:3]
        bullet_text = "\n".join([f"• {b}." for b in top_bullets]) if top_bullets else "• Content extracted successfully."
        
        fallback_text = (
            f"### Key Highlights:\n{bullet_text}\n\n"
            f"**Word Count:** ~{word_count} words | **Estimated Reading Time:** ~{reading_time_min} min"
        )
        return {
            "summary": fallback_text,
            "word_count": word_count,
            "reading_time_min": reading_time_min,
            "is_ai": False
        }

    # --- Feature 4: Interactive Chat with Document (Mini-RAG) ---
    @classmethod
    def chat_with_document(cls, document_text, query, history=None):
        """Answers questions grounded on the document text."""
        # Chunk or select relevant parts if text is long
        relevant_context = document_text[:5000]
        
        system_prompt = (
            "You are a helpful assistant answering questions about a user's downloaded file. "
            "Base your answers accurately on the provided file context. If information is not in the text, state so politely."
        )
        
        prompt = (
            f"File Content Context:\n\"\"\"\n{relevant_context}\n\"\"\"\n\n"
            f"User Question: {query}\n"
            f"Answer:"
        )

        reply = cls.call_llm(prompt, system_prompt=system_prompt, max_tokens=400, timeout=8)
        if reply:
            return reply

        # Fallback keyword match search
        matches = [line.strip() for line in document_text.splitlines() if any(w.lower() in line.lower() for w in query.split() if len(w) > 3)]
        if matches:
            return "Found related excerpts in file:\n\n> " + "\n> ".join(matches[:4])
        return "I could not find a direct answer in the file text without an active AI provider connected."

    # --- Feature 5: Natural Language Download Resolution ---
    @classmethod
    def resolve_natural_language_download(cls, prompt_text):
        """Parses natural language requests (e.g. 'download python 3.12 installer for windows')

        and extracts target software, version, and official download URL recommendations.
        """
        prompt = (
            f"The user typed a download query: '{prompt_text}'.\n"
            f"1. Identify the software name, version, and platform.\n"
            f"2. Provide the direct official download or project website URL.\n"
            f"Respond in JSON format with keys: 'software_name', 'suggested_filename', 'official_url', 'direct_link_hint'."
        )
        ai_resp = cls.call_llm(prompt, system_prompt="You are a software download helper. Return JSON only.", max_tokens=200, timeout=4)
        if ai_resp:
            try:
                # Find JSON block
                json_match = re.search(r'\{.*\}', ai_resp, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group(0))
                    if isinstance(parsed, dict) and ("official_url" in parsed or "direct_link_hint" in parsed):
                        return cls._validate_download_result(parsed)
            except Exception:
                pass

        # Offline heuristic fallback
        return cls._validate_download_result(cls._heuristic_resolve_download(prompt_text))

    @staticmethod
    def _validate_download_result(result):
        """Probe links in the NL worker so HTML/error pages never become installers."""
        if not isinstance(result, dict):
            return {}
        result = dict(result)
        for key in ("official_url", "direct_link_hint"):
            value = result.get(key)
            if not isinstance(value, str) or urllib.parse.urlparse(value).scheme not in ("http", "https"):
                result[key] = ""
        url = result.get("direct_link_hint")
        if not url:
            return result
        try:
            with requests.get(url, stream=True, timeout=(5, 10), headers={
                "Range": "bytes=0-511", "Accept-Encoding": "identity"
            }) as response:
                response.raise_for_status()
                mime = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
                sample = next(response.iter_content(512), b"").lstrip().lower()
                if (response.status_code not in (200, 206)
                        or mime in ("text/html", "application/xhtml+xml", "application/json")
                        or sample.startswith((b"<!doctype html", b"<html"))):
                    result["direct_link_hint"] = ""
                    if not result.get("official_url"):
                        result["official_url"] = url
        except requests.RequestException:
            result["direct_link_hint"] = ""
        return result

    @classmethod
    def _heuristic_resolve_download(cls, prompt_text):
        """Offline heuristic lookup for popular software queries."""
        if not prompt_text:
            return None

        p_lower = prompt_text.lower().strip()

        # Extract potential version number (e.g. 3.12, 3.12.0)
        ver_match = re.search(r'\b(\d+(?:\.\d+)+)\b', p_lower)
        version = ver_match.group(1) if ver_match else None

        # Known software database
        software_map = [
            (
                r'\bpython\b',
                "Python",
                f"python-{version or '3.12.2'}-amd64.exe",
                "https://www.python.org/downloads/",
                f"https://www.python.org/ftp/python/{version or '3.12.2'}/python-{version or '3.12.2'}-amd64.exe"
            ),
            (
                r'\bvlc\b',
                "VLC Media Player",
                f"vlc-{version or '3.0.20'}-win64.exe",
                "https://www.videolan.org/vlc/",
                f"https://get.videolan.org/vlc/{version or '3.0.20'}/win64/vlc-{version or '3.0.20'}-win64.exe"
            ),
            (
                r'\b(?:vs\s*code|visual\s*studio\s*code)\b',
                "Visual Studio Code",
                "VSCodeUserSetup-x64.exe",
                "https://code.visualstudio.com/",
                "https://update.code.visualstudio.com/latest/win32-x64-user/stable"
            ),
            (
                r'\b(?:chrome|google\s*chrome)\b',
                "Google Chrome",
                "ChromeSetup.exe",
                "https://www.google.com/chrome/",
                "https://dl.google.com/chrome/install/ChromeSetup.exe"
            ),
            (
                r'\bgit\b',
                "Git",
                f"Git-{version or '2.44.0'}-64-bit.exe",
                "https://git-scm.com/downloads",
                ""
            ),
            (
                r'\b(?:node|node\.?js)\b',
                "Node.js",
                f"node-v{version or '20.11.1'}-x64.msi",
                "https://nodejs.org/en/download",
                f"https://nodejs.org/dist/latest/node-x64.msi"
            ),
            (
                r'\bblender\b',
                "Blender",
                f"blender-{version or '4.0.2'}-windows-x64.msi",
                "https://www.blender.org/download/",
                ""
            ),
            (
                r'\b(?:7[\s-]?zip|7z)\b',
                "7-Zip",
                "7z2408-x64.exe",
                "https://www.7-zip.org/download.html",
                "https://www.7-zip.org/a/7z2408-x64.exe"
            ),
            (
                r'\b(?:firefox|mozilla\s*firefox)\b',
                "Mozilla Firefox",
                "Firefox Installer.exe",
                "https://www.mozilla.org/firefox/",
                "https://download.mozilla.org/?product=firefox-stub&os=win64"
            ),
            (
                r'\b(?:obs|obs\s*studio)\b',
                "OBS Studio",
                f"OBS-Studio-{version or '30.0.2'}-Full-Installer-x64.exe",
                "https://obsproject.com/",
                ""
            ),
            (
                r'\bnotepad\+\+(?!\w)',
                "Notepad++",
                "npp.Installer.x64.exe",
                "https://notepad-plus-plus.org/",
                ""
            ),
            (
                r'\btelegram\b',
                "Telegram Desktop",
                "tsetup.exe",
                "https://desktop.telegram.org/",
                "https://telegram.org/dl/desktop/win64"
            ),
            (
                r'\bdiscord\b',
                "Discord",
                "DiscordSetup.exe",
                "https://discord.com/download",
                "https://discord.com/api/download?platform=win"
            ),
        ]

        for pattern, name, filename, url, hint in software_map:
            if re.search(pattern, p_lower):
                return {
                    "software_name": name,
                    "suggested_filename": filename,
                    "official_url": url,
                    "direct_link_hint": hint
                }

        # Generic heuristic: extract cleaned title
        clean_words = [w for w in re.split(r'\s+', p_lower) if w not in ('download', 'installer', 'setup', 'for', 'windows', 'pc', 'latest', 'version', 'get', 'the')]
        app_name = " ".join(clean_words).title() if clean_words else "Requested Application"
        return {
            "software_name": app_name,
            "suggested_filename": f"{app_name.replace(' ', '_')}_Setup.exe",
            "official_url": f"https://www.google.com/search?q={urllib.parse.quote(prompt_text)}",
            "direct_link_hint": ""
        }
