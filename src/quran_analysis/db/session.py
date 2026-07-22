from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from quran_analysis.config import settings


def get_engine():
    return create_engine(settings.database_url)


def get_session_local():
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
