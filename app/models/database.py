import os
import sys
from sqlalchemy import create_engine
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

def init_db():
    from . import schemas
    Base.metadata.create_all(bind=engine)

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
    except Exception:
        pass

def get_all_tasks():
    from .schemas import DownloadTask
    with SessionLocal() as session:
        return session.query(DownloadTask).order_by(DownloadTask.created_at.desc()).all()

def create_task(url, filename, save_path):
    from .schemas import DownloadTask
    with SessionLocal() as session:
        try:
            task = DownloadTask(url=url, filename=filename, save_path=save_path, status="pending")
            session.add(task)
            session.commit()
            session.refresh(task)
            return task.id
        except Exception:
            session.rollback()
            raise

def update_task_progress(task_id, downloaded_size, total_size, status=None):
    if not task_id: return
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

