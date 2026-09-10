import os
from app.models.database import get_all_rules, get_setting
from app.services.ai_client import AIClient

class SmartRouter:
    """Routes downloads to appropriate folders based on user Smart Rules and AI classification."""

    @classmethod
    def route_download(cls, url, filename, default_dir=None):
        if not default_dir:
            default_dir = os.path.join(os.path.expanduser("~"), "Downloads")

        enable_routing = get_setting("enable_ai_smart_routing", "true").lower() in ("true", "1", "yes")
        if not enable_routing:
            return default_dir, "General"

        ext = os.path.splitext(filename)[1].lower() if "." in filename else ""
        fn_lower = filename.lower()

        # 1. Evaluate User-Defined Active Rules in Database
        try:
            rules = get_all_rules()
            for rule in rules:
                if not getattr(rule, 'is_active', 1):
                    continue

                cond_type = getattr(rule, 'condition_type', '')
                cond_val = getattr(rule, 'condition_value', '').strip()
                dest = getattr(rule, 'destination_path', '').strip()

                if not dest:
                    continue

                # Condition: File Extension Match (.pdf, .zip, etc.)
                if cond_type == "ext":
                    exts = [e.strip().lower() for e in cond_val.split(',')]
                    if ext and any(ext == e or ext == f".{e.lstrip('.')}" for e in exts):
                        os.makedirs(dest, exist_ok=True)
                        return dest, getattr(rule, 'name', 'Custom Rule')

                # Condition: Filename Contains
                elif cond_type == "contains":
                    if cond_val.lower() in fn_lower:
                        os.makedirs(dest, exist_ok=True)
                        return dest, getattr(rule, 'name', 'Custom Rule')

                # Condition: AI Semantic Category
                elif cond_type == "ai_category":
                    ai_cat = AIClient.classify_category(filename, url, ext)
                    if cond_val.lower() in ai_cat.lower() or ai_cat.lower() in cond_val.lower():
                        os.makedirs(dest, exist_ok=True)
                        return dest, ai_cat
        except Exception:
            pass

        # 2. Default Automatic Semantic Categorization
        cat = AIClient.classify_category(filename, url, ext)
        cat_folder = os.path.join(default_dir, cat)
        try:
            os.makedirs(cat_folder, exist_ok=True)
            return cat_folder, cat
        except Exception:
            return default_dir, cat
