"""
magnetar.db
-----------
Database engine factory supporting SQLite, PostgreSQL, MySQL, and MariaDB.
All four backends work via the MS_DATABASE_URL environment variable:

  sqlite:///magnetar.db
  postgresql://user:pass@host:5432/magnetar
  mysql+pymysql://user:pass@host:3306/magnetar
  mariadb+pymysql://user:pass@host:3306/magnetar
"""

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager
from typing import Dict, Any

from .models import Base

SessionFactory = sessionmaker(expire_on_commit=False)

def get_engine(url: str):
    """
    Creates an engine, sets check_same_thread=False for SQLite, 
    and pool_pre_ping=True for all engines.
    """
    kwargs: Dict[str, Any] = {'pool_pre_ping': True}
    
    if url.startswith('sqlite'):
        kwargs['connect_args'] = {'check_same_thread': False}
        
    engine = create_engine(url, **kwargs)
    return engine

def init_db(engine) -> None:
    """
    Creates all tables if they do not exist and binds the SessionFactory.
    """
    Base.metadata.create_all(engine)
    SessionFactory.configure(bind=engine)

@contextmanager
def get_db_session():
    """
    Context manager that yields a session and commits on success 
    or rolls back on error.
    """
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

def get_db_info(engine) -> dict:
    """
    Returns dictionary with dialect, url_display (password hidden), and table_count.
    """
    url_display = engine.url.render_as_string(hide_password=True)
    inspector = inspect(engine)
    table_count = len(inspector.get_table_names())
    
    return {
        "dialect": engine.dialect.name,
        "url_display": url_display,
        "table_count": table_count
    }
