from datetime import date, datetime
from typing import List, Optional
from sqlalchemy import String, Integer, DateTime, Boolean, Date, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func

class Base(DeclarativeBase):
    pass

class Hit(Base):
    __tablename__ = 'hits'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domain: Mapped[str] = mapped_column(String(255), default='example.com', index=True)
    ip: Mapped[str] = mapped_column(String(45), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    method: Mapped[Optional[str]] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[Optional[int]] = mapped_column(Integer)
    bytes_sent: Mapped[Optional[int]] = mapped_column(Integer)
    referer: Mapped[Optional[str]] = mapped_column(String(2048))
    user_agent: Mapped[Optional[str]] = mapped_column(String(2048))
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    
    __table_args__ = (
        UniqueConstraint('ip', 'occurred_at', 'method', 'path', 'domain', name='uq_hit_identity'),
    )

    def __repr__(self) -> str:
        return f"<Hit id={self.id} domain='{self.domain}' ip='{self.ip}' path='{self.path}'>"

class Session(Base):
    __tablename__ = 'sessions'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domain: Mapped[str] = mapped_column(String(255), default='example.com', index=True)
    visitor_ip: Mapped[str] = mapped_column(String(45), nullable=False, index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    entry_path: Mapped[Optional[str]] = mapped_column(String(2048))
    exit_path: Mapped[Optional[str]] = mapped_column(String(2048))
    country: Mapped[Optional[str]] = mapped_column(String(100))
    country_code: Mapped[Optional[str]] = mapped_column(String(2))
    
    journey_steps: Mapped[List["JourneyStep"]] = relationship("JourneyStep", back_populates="session", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Session id={self.id} domain='{self.domain}' ip='{self.visitor_ip}' hits={self.hit_count}>"

class Visitor(Base):
    __tablename__ = 'visitors'
    
    ip: Mapped[str] = mapped_column(String(45), primary_key=True)
    first_seen: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime)
    total_sessions: Mapped[int] = mapped_column(Integer, default=0)
    total_hits: Mapped[int] = mapped_column(Integer, default=0)
    country: Mapped[Optional[str]] = mapped_column(String(100))
    country_code: Mapped[Optional[str]] = mapped_column(String(2))
    city: Mapped[Optional[str]] = mapped_column(String(100))

    def __repr__(self) -> str:
        return f"<Visitor ip='{self.ip}' sessions={self.total_sessions}>"

class DailySummary(Base):
    __tablename__ = 'daily_summaries'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domain: Mapped[str] = mapped_column(String(255), default='example.com', index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    total_hits: Mapped[Optional[int]] = mapped_column(Integer)
    unique_ips: Mapped[Optional[int]] = mapped_column(Integer)
    human_hits: Mapped[Optional[int]] = mapped_column(Integer)
    bot_hits: Mapped[Optional[int]] = mapped_column(Integer)
    top_country: Mapped[Optional[str]] = mapped_column(String(100))
    top_article: Mapped[Optional[str]] = mapped_column(String(2048))

    __table_args__ = (
        UniqueConstraint('domain', 'date', name='uq_daily_summary_domain_date'),
    )

    def __repr__(self) -> str:
        return f"<DailySummary domain='{self.domain}' date='{self.date}' hits={self.total_hits}>"

class Event(Base):
    __tablename__ = 'events'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domain: Mapped[str] = mapped_column(String(255), default='example.com', index=True)
    hit_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey('hits.id'))
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    path: Mapped[Optional[str]] = mapped_column(String(2048))
    ip: Mapped[Optional[str]] = mapped_column(String(45))
    occurred_at: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)

    def __repr__(self) -> str:
        return f"<Event id={self.id} domain='{self.domain}' type='{self.event_type}'>"

class JourneyStep(Base):
    __tablename__ = 'journey_steps'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey('sessions.id'), index=True, nullable=False)
    step_index: Mapped[Optional[int]] = mapped_column(Integer)
    path: Mapped[Optional[str]] = mapped_column(String(2048))
    occurred_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    session: Mapped["Session"] = relationship("Session", back_populates="journey_steps")

    def __repr__(self) -> str:
        return f"<JourneyStep id={self.id} session_id={self.session_id} step={self.step_index}>"

class FunnelDef(Base):
    __tablename__ = 'funnel_defs'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domain: Mapped[str] = mapped_column(String(255), default='all', index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    
    steps: Mapped[List["FunnelStep"]] = relationship("FunnelStep", back_populates="funnel", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<FunnelDef id={self.id} domain='{self.domain}' name='{self.name}'>"

class FunnelStep(Base):
    __tablename__ = 'funnel_steps'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    funnel_id: Mapped[int] = mapped_column(Integer, ForeignKey('funnel_defs.id', ondelete='CASCADE'), nullable=False)
    step_index: Mapped[Optional[int]] = mapped_column(Integer)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    path_pattern: Mapped[Optional[str]] = mapped_column(String(2048))
    
    funnel: Mapped["FunnelDef"] = relationship("FunnelDef", back_populates="steps")

    def __repr__(self) -> str:
        return f"<FunnelStep id={self.id} funnel_id={self.funnel_id} step={self.step_index}>"

class SyncConfig(Base):
    __tablename__ = 'sync_config'
    
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(String(2048))

    def __repr__(self) -> str:
        return f"<SyncConfig key='{self.key}' value='{self.value}'>"
