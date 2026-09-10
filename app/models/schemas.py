from sqlalchemy import Column, Integer, String, BigInteger, DateTime, Text
from datetime import datetime, timezone
from .database import Base

class DownloadTask(Base):
    __tablename__ = "download_tasks"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, index=True)
    filename = Column(String)
    save_path = Column(String)
    total_size = Column(BigInteger, default=0)
    downloaded_size = Column(BigInteger, default=0)
    status = Column(String, default="pending")  # pending, downloading, paused, completed, error
    category = Column(String, default="General")
    threat_level = Column(String, default="safe")  # safe, warning, danger
    ai_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class SmartRule(Base):
    __tablename__ = "smart_rules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, default="Custom Rule")
    condition_type = Column(String)  # ext, contains, ai_category
    condition_value = Column(String)
    destination_path = Column(String)
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True, index=True)
    value = Column(Text, nullable=True)
