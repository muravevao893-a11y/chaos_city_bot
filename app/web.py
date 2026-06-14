from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select, text
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.game import (
    city_payload,
    create_daily_event,
    event_payload,
    get_or_create_city,
    get_or_create_player,
    join_city,
    recent_logs,
    resolve_event,
    start_war,
    top_cities,
    top_players,
    validate_telegram_init_data,
    vote_event,
    work,
)
from app.models import City, CityEvent, Player

router = APIRouter(prefix="/api", tags=["api"])


def get_db():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class TelegramAuthRequest(BaseModel):
    init_data: str = Field(default="")


class DemoUserRequest(BaseModel):
    telegram_user_id: int = Field(default=10001)
    username: str | None = Field(default="demo_user")
    first_name: str = Field(default="Demo")
    chat_id: int = Field(default=-1000000001)
    chat_title: str = Field(default="Demo Chaos Chat")


class VoteRequest(BaseModel):
    telegram_user_id: int
    option: int


class RaidRequest(BaseModel):
    defender_code: str


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "chatograd-bot"}


@router.get("/ready")
def ready(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ready", "database": "ok"}


@router.post("/auth/telegram")
def auth_telegram(payload: TelegramAuthRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    data = validate_telegram_init_data(payload.init_data)
    if not data or "user" not in data:
        raise HTTPException(status_code=401, detail="Invalid Telegram initData")

    user = data["user"]
    player, created, reward = get_or_create_player(
        db,
        telegram_user_id=int(user["id"]),
        username=user.get("username"),
        first_name=user.get("first_name") or "Игрок",
    )
    return {
        "ok": True,
        "created": created,
        "reward": reward,
        "player": player_payload(player),
    }


@router.post("/demo/bootstrap")
def demo_bootstrap(payload: DemoUserRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    city, _ = get_or_create_city(db, payload.chat_id, payload.chat_title)
    player, _, _ = get_or_create_player(db, payload.telegram_user_id, payload.username, payload.first_name)
    join_city(db, city, player)
    event = create_daily_event(db, city, force=False)
    active_event = event or db.scalar(
        select(CityEvent).where(CityEvent.city_id == city.id, CityEvent.resolved_at.is_(None)).order_by(desc(CityEvent.created_at))
    )
    return dashboard_payload(db, city, player, active_event)


@router.get("/cities/top")
def api_top_cities(db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"cities": top_cities(db, limit=20)}


@router.get("/cities/{chat_id}")
def api_city(chat_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    city = db.scalar(select(City).where(City.chat_id == chat_id))
    if not city:
        raise HTTPException(status_code=404, detail="City not found")
    active_event = db.scalar(
        select(CityEvent).where(CityEvent.city_id == city.id, CityEvent.resolved_at.is_(None)).order_by(desc(CityEvent.created_at))
    )
    return {
        "city": city_payload(db, city),
        "top_players": top_players(db, city, limit=20),
        "event": event_payload(active_event),
        "logs": recent_logs(db, city.id, limit=20),
    }


@router.post("/cities/{chat_id}/work")
def api_work(chat_id: int, payload: DemoUserRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    city = db.scalar(select(City).where(City.chat_id == chat_id))
    if not city:
        city, _ = get_or_create_city(db, chat_id, payload.chat_title)
    player, _, _ = get_or_create_player(db, payload.telegram_user_id, payload.username, payload.first_name)
    join_city(db, city, player)
    result = work(db, city, player)
    return {
        "result": result.__dict__,
        "city": city_payload(db, city),
        "player": player_payload(player),
    }


@router.post("/cities/{chat_id}/event")
def api_event(chat_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    city = db.scalar(select(City).where(City.chat_id == chat_id))
    if not city:
        raise HTTPException(status_code=404, detail="City not found")
    event = create_daily_event(db, city, force=False)
    if event is None:
        event = db.scalar(select(CityEvent).where(CityEvent.city_id == city.id, CityEvent.resolved_at.is_(None)).order_by(desc(CityEvent.created_at)))
    return {"event": event_payload(event)}


@router.post("/cities/{chat_id}/vote")
def api_vote(chat_id: int, payload: VoteRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    city = db.scalar(select(City).where(City.chat_id == chat_id))
    if not city:
        raise HTTPException(status_code=404, detail="City not found")
    player = db.scalar(select(Player).where(Player.telegram_user_id == payload.telegram_user_id))
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    event, text = vote_event(db, city, player, payload.option)
    return {"message": text, "event": event_payload(event)}


@router.post("/cities/{chat_id}/resolve")
def api_resolve(chat_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    city = db.scalar(select(City).where(City.chat_id == chat_id))
    if not city:
        raise HTTPException(status_code=404, detail="City not found")
    text = resolve_event(db, city)
    return {"message": text, "city": city_payload(db, city)}


@router.post("/cities/{chat_id}/raid")
def api_raid(chat_id: int, payload: RaidRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    city = db.scalar(select(City).where(City.chat_id == chat_id))
    if not city:
        raise HTTPException(status_code=404, detail="City not found")
    war, text = start_war(db, city, payload.defender_code)
    return {
        "message": text,
        "war": None if not war else {
            "attacker_score": war.attacker_score,
            "defender_score": war.defender_score,
            "status": war.status,
        },
        "city": city_payload(db, city),
    }


def player_payload(player: Player) -> dict[str, Any]:
    return {
        "id": player.id,
        "telegram_user_id": player.telegram_user_id,
        "username": player.username,
        "first_name": player.first_name,
        "role": player.role,
        "coins": player.coins,
        "xp": player.xp,
        "energy": player.energy,
        "ref_code": player.ref_code,
        "created_at": player.created_at.isoformat(),
    }


def dashboard_payload(db: Session, city: City, player: Player, active_event: CityEvent | None) -> dict[str, Any]:
    return {
        "city": city_payload(db, city),
        "player": player_payload(player),
        "top_players": top_players(db, city, limit=12),
        "top_cities": top_cities(db, limit=10),
        "event": event_payload(active_event),
        "logs": recent_logs(db, city.id, limit=12),
    }
