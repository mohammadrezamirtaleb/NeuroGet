from sqlalchemy import Column, Integer, String, Float, DateTime
from datetime import datetime
from .database import Base

class DownloadTask(Base):
    __tablename__ = "download_tasks"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, index=True)
    filename = Column(String)
    save_path = Column(String)
    total_size = Column(Float, default=0)
    downloaded_size = Column(Float, default=0)
    status = Column(String, default="pending") # pending, downloading, paused, completed, error
    created_at = Column(DateTime, default=datetime.utcnow)
    
class SmartRule(Base):
    __tablename__ = "smart_rules"
    
    id = Column(Integer, primary_key=True, index=True)
    condition_type = Column(String) # ext, contains, ai_category
    condition_value = Column(String)
    destination_path = Column(String)
