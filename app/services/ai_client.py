import os
import re
import json
import time
import requests
import urllib.parse
from app.models.database import get_setting

# Provider endpoints configuration
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_LMSTUDIO_HOST = "http://localhost:1234/v1"
DEFAULT_GPT4ALL_HOST = "http://localhost:4891/v1"

class AIClient:
    """Universal AI Client supporting Local (Ollama, LM Studio, GPT4All) and Cloud LLMs

    with automatic, instant heuristic fallbacks.
    """

    @classmethod
    def get_configured_provider(cls):
        return get_setting("ai_provider", "Local: Ollama")

    @classmethod
    def get_api_key(cls):
        return get_setting("ai_api_key", "")

    @classmethod
    def get_model_name(cls):
        return get_setting("ai_model", "")

    @classmethod
    def call_llm(cls, prompt, system_prompt=None, max_tokens=500, timeout=6):
        """Sends prompt to the active AI provider. Returns response text or None on failure."""
        provider = cls.get_configured_provider()
        api_key = cls.get_api_key()
        model = cls.get_model_name()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # 1. Local: Ollama
        if "ollama" in provider.lower():
            # Determine model
            ollama_model = model
            if not ollama_model or "local:" in ollama_model.lower():
                if "-" in provider:
                    ollama_model = provider.split("-")[-1].strip()
                else:
                    from app.services.ai_scanner import LocalAIDetector
                    disk_models = LocalAIDetector._scan_ollama_disk_manifests()
                    ollama_model = disk_models[0] if disk_models else ""

            payload = {
                "model": ollama_model,
                "prompt": f"{system_prompt + '\n\n' if system_prompt else ''}{prompt}",
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": max_tokens}
            }
            try:
                res = requests.post(f"{DEFAULT_OLLAMA_HOST}/api/generate", json=payload, timeout=timeout)
                if res.status_code == 200:
                    return res.json().get("response", "").strip()
            except Exception:
                try:
                    import shutil
                    import subprocess
                    ollama_bin = shutil.which("ollama") or os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe")
                    if ollama_bin and os.path.exists(ollama_bin):
                        subprocess.Popen(
                            [ollama_bin, "serve"],
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                        )
                        time.sleep(1.5)
                        res = requests.post(f"{DEFAULT_OLLAMA_HOST}/api/generate", json=payload, timeout=timeout)
                        if res.status_code == 200:
                            return res.json().get("response", "").strip()
                except Exception:
                    pass

        # 2. Local: LM Studio or GPT4All (OpenAI-compatible)
        if "lm studio" in provider.lower() or "gpt4all" in provider.lower():
            host = DEFAULT_LMSTUDIO_HOST if "lm studio" in provider.lower() else DEFAULT_GPT4ALL_HOST
            try:
                payload = {
                    "messages": messages,
                    "temperature": 0.3,
                    "max_tokens": max_tokens
                }
                res = requests.post(f"{host}/chat/completions", json=payload, timeout=timeout)
                if res.status_code == 200:
                    data = res.json()
                    choices = data.get("choices", [])
                    if choices:
                        return choices[0].get("message", {}).get("content", "").strip()
            except Exception:
                pass

        # 3. Cloud: OpenAI / OpenRouter / Groq / OpenCode Zen
        if any(p in provider.lower() for p in ["openai", "openrouter", "groq", "opencode", "copilot"]):
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
                res = requests.post(endpoint, json=payload, headers=headers, timeout=timeout)
                if res.status_code == 200:
                    data = res.json()
                    choices = data.get("choices", [])
                    if choices:
                        return choices[0].get("message", {}).get("content", "").strip()
            except Exception:
                pass

        # 4. Cloud: Google Gemini
        if "gemini" in provider.lower() or "google" in provider.lower():
            if not api_key:
                return None
            try:
                gemini_model = model or "gemini-1.5-flash"
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={api_key}"
                full_text = f"{system_prompt + '\n\n' if system_prompt else ''}{prompt}"
                payload = {
                    "contents": [{"parts": [{"text": full_text}]}],
                    "generationConfig": {"temperature": 0.3, "maxOutputTokens": max_tokens}
                }
                res = requests.post(url, json=payload, timeout=timeout)
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            return parts[0].get("text", "").strip()
            except Exception:
                pass

        return None

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
        name_parts = os.path.splitext(raw_name)
        base_name = name_parts[0]
        ext = name_parts[1]

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
                    return json.loads(json_match.group(0))
            except Exception:
                pass
        return None
