import os
import sys
import sqlite3
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

# Store DB in AppData to avoid PermissionError in Program Files
app_data = os.environ.get('LOCALAPPDATA', os.path.expanduser('~'))
base_dir = os.path.join(app_data, 'NeuroGet')
os.makedirs(base_dir, exist_ok=True)

db_path = os.path.join(base_dir, 'downloads.db')
db_path_clean = db_path.replace('\\', '/')
DATABASE_URL = f"sqlite:///{db_path_clean}"

# Adding increased timeout to avoid "database is locked" errors during concurrency
engine = create_engine(DATABASE_URL, echo=False, connect_args={'timeout': 30})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


def _migrate_db():
    """Ensure newly added columns exist in existing SQLite databases."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check download_tasks columns
        cursor.execute("PRAGMA table_info(download_tasks)")
        columns = [row[1] for row in cursor.fetchall()]
        if columns:
            if "category" not in columns:
                cursor.execute("ALTER TABLE download_tasks ADD COLUMN category TEXT DEFAULT 'General'")
            if "threat_level" not in columns:
                cursor.execute("ALTER TABLE download_tasks ADD COLUMN threat_level TEXT DEFAULT 'safe'")
            if "ai_summary" not in columns:
                cursor.execute("ALTER TABLE download_tasks ADD COLUMN ai_summary TEXT")

        # Check smart_rules columns
        cursor.execute("PRAGMA table_info(smart_rules)")
        s_cols = [row[1] for row in cursor.fetchall()]
        if s_cols:
            if "name" not in s_cols:
                cursor.execute("ALTER TABLE smart_rules ADD COLUMN name TEXT DEFAULT 'Custom Rule'")
            if "is_active" not in s_cols:
                cursor.execute("ALTER TABLE smart_rules ADD COLUMN is_active INTEGER DEFAULT 1")
            if "created_at" not in s_cols:
                cursor.execute("ALTER TABLE smart_rules ADD COLUMN created_at TIMESTAMP")

        conn.commit()
        conn.close()
    except Exception:
        pass


def init_db():
    from . import schemas
    Base.metadata.create_all(bind=engine)
    _migrate_db()
    _seed_default_rules_if_empty()


def _seed_default_rules_if_empty():
    from .schemas import SmartRule
    with SessionLocal() as session:
        try:
            count = session.query(SmartRule).count()
            if count == 0:
                downloads_dir = os.path.join(os.path.expanduser("~"), "Downloads")
                defaults = [
                    SmartRule(
                        name="Documents & PDFs",
                        condition_type="ext",
                        condition_value=".pdf, .docx, .doc, .txt, .epub",
                        destination_path=os.path.join(downloads_dir, "Documents"),
                        is_active=1
                    ),
                    SmartRule(
                        name="Software & Installers",
                        condition_type="ext",
                        condition_value=".exe, .msi, .apk, .dmg, .iso",
                        destination_path=os.path.join(downloads_dir, "Software"),
                        is_active=1
                    ),
                    SmartRule(
                        name="Media & Videos",
                        condition_type="ext",
                        condition_value=".mp4, .mkv, .avi, .mov, .mp3, .wav",
                        destination_path=os.path.join(downloads_dir, "Media"),
                        is_active=1
                    ),
                    SmartRule(
                        name="Archives & Backups",
                        condition_type="ext",
                        condition_value=".zip, .rar, .7z, .tar, .gz",
                        destination_path=os.path.join(downloads_dir, "Archives"),
                        is_active=1
                    ),
                    SmartRule(
                        name="AI Course & Tutorial Match",
                        condition_type="ai_category",
                        condition_value="Education / Course",
                        destination_path=os.path.join(downloads_dir, "Education"),
                        is_active=1
                    ),
                ]
                session.add_all(defaults)
                session.commit()
        except Exception:
            session.rollback()


def clear_download_history():
    from .schemas import DownloadTask
    with SessionLocal() as session:
        try:
            session.query(DownloadTask).filter(DownloadTask.status == "completed").delete()
            session.commit()
        except Exception:
            session.rollback()
            raise


def reset_database():
    from . import schemas
    try:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        _seed_default_rules_if_empty()
    except Exception:
        pass


# --- Download Task Operations ---

def get_all_tasks():
    from .schemas import DownloadTask
    with SessionLocal() as session:
        return session.query(DownloadTask).order_by(DownloadTask.created_at.desc()).all()


def get_task_by_id(task_id):
    if not task_id:
        return None
    from .schemas import DownloadTask
    with SessionLocal() as session:
        return session.query(DownloadTask).filter(DownloadTask.id == task_id).first()


def create_task(url, filename, save_path, category="General", threat_level="safe"):
    from .schemas import DownloadTask
    with SessionLocal() as session:
        try:
            task = DownloadTask(
                url=url,
                filename=filename,
                save_path=save_path,
                category=category,
                threat_level=threat_level,
                status="pending"
            )
            session.add(task)
            session.commit()
            session.refresh(task)
            return task.id
        except Exception:
            session.rollback()
            raise


def update_task_progress(task_id, downloaded_size, total_size, status=None):
    if not task_id:
        return
    from .schemas import DownloadTask
    with SessionLocal() as session:
        try:
            task = session.query(DownloadTask).filter(DownloadTask.id == task_id).first()
            if task:
                task.downloaded_size = downloaded_size
                if total_size > 0:
                    task.total_size = total_size
                if status:
                    task.status = status
                session.commit()
        except Exception:
            session.rollback()


def update_task_metadata(task_id, filename=None, category=None, threat_level=None, ai_summary=None, save_path=None):
    if not task_id:
        return
    from .schemas import DownloadTask
    with SessionLocal() as session:
        try:
            task = session.query(DownloadTask).filter(DownloadTask.id == task_id).first()
            if task:
                if filename is not None:
                    task.filename = filename
                if category is not None:
                    task.category = category
                if threat_level is not None:
                    task.threat_level = threat_level
                if ai_summary is not None:
                    task.ai_summary = ai_summary
                if save_path is not None:
                    task.save_path = save_path
                session.commit()
        except Exception:
            session.rollback()


# --- Smart Rules Operations ---

def get_all_rules():
    from .schemas import SmartRule
    with SessionLocal() as session:
        return session.query(SmartRule).order_by(SmartRule.id.asc()).all()


def create_rule(name, condition_type, condition_value, destination_path, is_active=1):
    from .schemas import SmartRule
    with SessionLocal() as session:
        try:
            rule = SmartRule(
                name=name,
                condition_type=condition_type,
                condition_value=condition_value,
                destination_path=destination_path,
                is_active=is_active
            )
            session.add(rule)
            session.commit()
            session.refresh(rule)
            return rule.id
        except Exception:
            session.rollback()
            raise


def delete_rule(rule_id):
    from .schemas import SmartRule
    with SessionLocal() as session:
        try:
            session.query(SmartRule).filter(SmartRule.id == rule_id).delete()
            session.commit()
        except Exception:
            session.rollback()
            raise


def toggle_rule(rule_id, is_active):
    from .schemas import SmartRule
    with SessionLocal() as session:
        try:
            rule = session.query(SmartRule).filter(SmartRule.id == rule_id).first()
            if rule:
                rule.is_active = 1 if is_active else 0
                session.commit()
        except Exception:
            session.rollback()
            raise


# --- App Settings Operations ---

def get_setting(key, default=None):
    from .schemas import AppSetting
    with SessionLocal() as session:
        try:
            setting = session.query(AppSetting).filter(AppSetting.key == key).first()
            if setting and setting.value is not None:
                return setting.value
        except Exception:
            pass
    return default


def set_setting(key, value):
    from .schemas import AppSetting
    with SessionLocal() as session:
        try:
            setting = session.query(AppSetting).filter(AppSetting.key == key).first()
            if setting:
                setting.value = str(value) if value is not None else ""
            else:
                setting = AppSetting(key=key, value=str(value) if value is not None else "")
                session.add(setting)
            session.commit()
        except Exception:
            session.rollback()
