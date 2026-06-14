from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CityStatus(StrEnum):
    ACTIVE = "active"
    FROZEN = "frozen"


class WarStatus(StrEnum):
    ACTIVE = "active"
    FINISHED = "finished"


class AllianceStatus(StrEnum):
    ACTIVE = "active"
    BROKEN = "broken"


class City(Base):
    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    invite_code: Mapped[str] = mapped_column(String(24), unique=True, nullable=False, index=True)
    owner_telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    treasury: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    threat: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    buildings_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    trophies_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    shop_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    season_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    season_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_bot_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=CityStatus.ACTIVE.value, nullable=False)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="city", cascade="all, delete-orphan")
    events: Mapped[list["CityEvent"]] = relationship(back_populates="city", cascade="all, delete-orphan")


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str] = mapped_column(String(128), default="Игрок", nullable=False)
    role: Mapped[str] = mapped_column(String(64), default="Житель", nullable=False)
    coins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    energy: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    ref_code: Mapped[str] = mapped_column(String(24), unique=True, nullable=False, index=True)
    referred_by_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), nullable=True)
    last_work_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_daily_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    daily_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="player", cascade="all, delete-orphan", foreign_keys="Membership.player_id")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("city_id", "player_id", name="uq_membership_city_player"),
        Index("ix_membership_city_influence", "city_id", "influence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="CASCADE"), nullable=False)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    influence: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    reputation: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    special_title: Mapped[str | None] = mapped_column(String(64), nullable=True)
    civic_title: Mapped[str | None] = mapped_column(String(64), nullable=True)
    jailed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    convictions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    city: Mapped[City] = relationship(back_populates="memberships")
    player: Mapped[Player] = relationship(back_populates="memberships", foreign_keys=[player_id])


class CityEvent(Base):
    __tablename__ = "city_events"
    __table_args__ = (Index("ix_city_events_city_active", "city_id", "resolved_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="CASCADE"), nullable=False)
    event_key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    option_1: Mapped[str] = mapped_column(String(160), nullable=False)
    option_2: Mapped[str] = mapped_column(String(160), nullable=False)
    option_3: Mapped[str] = mapped_column(String(160), nullable=False)
    votes_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    city: Mapped[City] = relationship(back_populates="events")


class War(Base):
    __tablename__ = "wars"
    __table_args__ = (
        Index("ix_wars_defender_status_created", "defender_city_id", "status", "created_at"),
        Index("ix_wars_attacker_defender_status", "attacker_city_id", "defender_city_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attacker_city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="CASCADE"), nullable=False)
    defender_city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="CASCADE"), nullable=False)
    attacker_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    defender_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=WarStatus.ACTIVE.value, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CityAlliance(Base):
    __tablename__ = "city_alliances"
    __table_args__ = (
        UniqueConstraint("city_a_id", "city_b_id", name="uq_city_alliance_pair"),
        Index("ix_city_alliances_city_a_status", "city_a_id", "status"),
        Index("ix_city_alliances_city_b_status", "city_b_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    city_a_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="CASCADE"), nullable=False)
    city_b_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=AllianceStatus.ACTIVE.value, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CityReferral(Base):
    __tablename__ = "city_referrals"
    __table_args__ = (
        UniqueConstraint("invited_city_id", name="uq_city_referral_invited_city"),
        Index("ix_city_referrals_referrer", "referrer_city_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    referrer_city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="CASCADE"), nullable=False)
    invited_city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="CASCADE"), nullable=False)
    invite_code: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    reward_given: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ActionLog(Base):
    __tablename__ = "action_logs"
    __table_args__ = (Index("ix_action_logs_city_created", "city_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    city_id: Mapped[int | None] = mapped_column(ForeignKey("cities.id", ondelete="SET NULL"), nullable=True)
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
