import os
import zipfile
import tarfile
import re
from app.services.ai_client import AIClient

class ContentAnalyzer:
    """Extracts text, metadata, and structural insight from various file types

    to feed into the AI Summarizer and Chat (Mini-RAG).
    """

    @classmethod
    def analyze_file(cls, filepath):
        if not filepath or not os.path.exists(filepath):
            return {
                "error": "File does not exist on disk.",
                "summary": "File not found.",
                "word_count": 0,
                "reading_time_min": 0,
                "metadata": {}
            }

        extracted = cls.extract_file_content(filepath)
        text = extracted.get("text", "")
        file_type = extracted.get("type", "unknown")
        metadata = extracted.get("metadata", {})
        filename = os.path.basename(filepath)

        if file_type in ("text", "pdf", "subtitles"):
            if text:
                ai_result = AIClient.summarize_content(text, filename=filename)
                ai_result["metadata"] = metadata
                ai_result["type"] = file_type
                ai_result["raw_text"] = text
                return ai_result
            else:
                return {
                    "summary": "Document opened successfully, but contains no extractable text (it may contain scanned image pages).",
                    "word_count": 0,
                    "reading_time_min": 0,
                    "metadata": metadata,
                    "type": file_type,
                    "raw_text": ""
                }

        elif file_type == "archive":
            file_list = metadata.get("files", [])
            total_items = len(file_list)
            sample_files = "\n".join([f"  - {f}" for f in file_list[:12]])
            if total_items > 12:
                sample_files += f"\n  - ... and {total_items - 12} more items"

            summary = (
                f"### Archive Contents ({total_items} items):\n"
                f"{sample_files}\n\n"
                f"**Total Uncompressed Size:** {metadata.get('uncompressed_size_formatted', 'Unknown')}"
            )
            return {
                "summary": summary,
                "word_count": total_items,
                "reading_time_min": 1,
                "metadata": metadata,
                "type": file_type,
                "raw_text": "\n".join(file_list)
            }

        elif file_type == "media":
            summary = (
                f"### Media Asset Details:\n"
                f"• **Format:** {metadata.get('extension', '').upper()}\n"
                f"• **File Size:** {metadata.get('size_formatted', 'Unknown')}\n"
                f"• **Location:** `{filepath}`"
            )
            return {
                "summary": summary,
                "word_count": 0,
                "reading_time_min": 1,
                "metadata": metadata,
                "type": file_type,
                "raw_text": ""
            }

        else:
            summary = (
                f"### File Information:\n"
                f"• **Filename:** {filename}\n"
                f"• **Size:** {metadata.get('size_formatted', 'Unknown')}\n"
                f"• **Format:** {metadata.get('extension', '').upper() or 'Binary'}"
            )
            return {
                "summary": summary,
                "word_count": 0,
                "reading_time_min": 1,
                "metadata": metadata,
                "type": file_type,
                "raw_text": ""
            }

    @classmethod
    def extract_file_content(cls, filepath):
        ext = os.path.splitext(filepath)[1].lower()
        size = os.path.getsize(filepath)
        size_fmt = cls._format_size(size)

        metadata = {
            "filename": os.path.basename(filepath),
            "size": size,
            "size_formatted": size_fmt,
            "extension": ext
        }

        # 1. Text / Code / Markdown
        text_exts = {
            '.txt', '.md', '.markdown', '.py', '.js', '.ts', '.html', '.css',
            '.json', '.csv', '.xml', '.yaml', '.yml', '.ini', '.log', '.rst',
            '.c', '.cpp', '.h', '.java', '.cs', '.go', '.rs', '.sql', '.sh'
        }
        if ext in text_exts:
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read(50000)  # Read up to 50k chars for efficiency
                metadata["line_count"] = content.count('\n') + 1
                return {"type": "text", "text": content, "metadata": metadata}
            except Exception:
                pass

        # 2. Subtitles
        if ext in ('.srt', '.vtt', '.sub', '.ass'):
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    raw = f.read(50000)
                # Strip timestamps and indices
                cleaned_lines = []
                for line in raw.splitlines():
                    line = line.strip()
                    if not line or line.isdigit() or '-->' in line:
                        continue
                    cleaned_lines.append(line)
                clean_text = "\n".join(cleaned_lines)
                return {"type": "subtitles", "text": clean_text, "metadata": metadata}
            except Exception:
                pass

        # 3. PDF extraction
        if ext == '.pdf':
            text = cls._extract_pdf_text(filepath)
            return {"type": "pdf", "text": text, "metadata": metadata}

        # 4. Archives (.zip, .tar, .gz)
        if ext == '.zip':
            try:
                with zipfile.ZipFile(filepath, 'r') as zf:
                    infolist = zf.infolist()
                    files = [info.filename for info in infolist]
                    uncompressed = sum(info.file_size for info in infolist)
                    metadata["files"] = files
                    metadata["item_count"] = len(files)
                    metadata["uncompressed_size"] = uncompressed
                    metadata["uncompressed_size_formatted"] = cls._format_size(uncompressed)
                    return {"type": "archive", "text": "\n".join(files), "metadata": metadata}
            except Exception:
                pass

        if ext in ('.tar', '.gz', '.tgz', '.bz2'):
            try:
                with tarfile.open(filepath, 'r:*') as tf:
                    members = tf.getmembers()
                    files = [m.name for m in members]
                    uncompressed = sum(m.size for m in members)
                    metadata["files"] = files
                    metadata["item_count"] = len(files)
                    metadata["uncompressed_size"] = uncompressed
                    metadata["uncompressed_size_formatted"] = cls._format_size(uncompressed)
                    return {"type": "archive", "text": "\n".join(files), "metadata": metadata}
            except Exception:
                pass

        # 5. Media (Video / Audio / Image)
        if ext in ('.mp4', '.mkv', '.avi', '.mov', '.mp3', '.wav', '.flac', '.png', '.jpg', '.jpeg'):
            return {"type": "media", "text": "", "metadata": metadata}

        return {"type": "binary", "text": "", "metadata": metadata}

    @classmethod
    def _extract_pdf_text(cls, filepath):
        """Extracts text streams from PDF without external heavy dependencies."""
        try:
            # Try pypdf if installed
            import pypdf
            reader = pypdf.PdfReader(filepath)
            text_pages = []
            for i, page in enumerate(reader.pages[:20]):  # First 20 pages
                t = page.extract_text()
                if t:
                    text_pages.append(f"--- Page {i+1} ---\n" + t)
            return "\n\n".join(text_pages)
        except Exception:
            pass

        # Fallback binary text stream scanning
        try:
            with open(filepath, 'rb') as f:
                raw = f.read(100000)
            # Find ascii strings in binary
            matches = re.findall(rb'[\x20-\x7E]{4,}', raw)
            decoded = [m.decode('latin-1', errors='ignore') for m in matches if not m.startswith((b'stream', b'xref', b'trailer', b'obj'))]
            return "\n".join(decoded[:200])
        except Exception:
            return ""

    @staticmethod
    def _format_size(bytes_size):
        if bytes_size <= 0:
            return "0 B"
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.1f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.1f} PB"
