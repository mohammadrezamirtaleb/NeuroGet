from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///downloads.db"

engine = create_engine(DATABASE_URL, echo=False, connect_args={'timeout': 15})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

def init_db():
    from . import schemas
    Base.metadata.create_all(bind=engine)

def clear_download_history():
    from .schemas import DownloadTask
    with SessionLocal() as session:
        session.query(DownloadTask).filter(DownloadTask.status == "completed").delete()
        session.commit()

def reset_database():
    from . import schemas
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

def create_task(url, filename, save_path):
    from .schemas import DownloadTask
    with SessionLocal() as session:
        task = DownloadTask(url=url, filename=filename, save_path=save_path, status="pending")
        session.add(task)
        session.commit()
        session.refresh(task)
        return task.id

def update_task_progress(task_id, downloaded_size, total_size, status=None):
    if not task_id: return
    from .schemas import DownloadTask
    with SessionLocal() as session:
        task = session.query(DownloadTask).filter(DownloadTask.id == task_id).first()
        if task:
            task.downloaded_size = downloaded_size
            if total_size > 0:
                task.total_size = total_size
            if status:
                task.status = status
            session.commit()

