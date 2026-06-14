import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.game import (
    build_city_building,
    building_payload,
    build_newspaper,
    create_court_event,
    create_daily_event,
    create_drama_event,
    create_mayor_election,
    get_or_create_city,
    get_or_create_player,
    help_city_quest,
    join_city,
    player_profile,
    quest_payload,
    resolve_event,
    start_war,
    create_raid_challenge,
    active_incoming_raids,
    resolve_raid_challenge,
    get_city_trophies,
    appoint_city_official,
    city_officials,
    weekly_summary,
    top_players,
    top_cities,
    collect_daily_reward,
    daily_payload,
    buy_shop_item,
    shop_payload,
    season_payload,
    maybe_roll_season,
    vote_event,
    work,
    FOUNDER_TITLE,
)


def make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)()


class GameLogicTest(unittest.TestCase):
    def test_city_join_work_event_and_war_flow(self):
        db = make_session()

        city, created = get_or_create_city(db, -1001, "Alpha Chat")
        self.assertTrue(created)
        player, created_player, _ = get_or_create_player(db, 1, "alice", "Alice")
        self.assertTrue(created_player)

        membership, joined = join_city(db, city, player)
        self.assertTrue(joined)
        self.assertEqual(membership.influence, 1)

        result = work(db, city, player, cooldown_hours=0)
        self.assertGreater(result.coins, 0)
        self.assertGreater(city.treasury, 25)

        event = create_daily_event(db, city, force=True)
        self.assertIsNotNone(event)
        event, message = vote_event(db, city, player, 1)
        self.assertIn("Голос принят", message)

        top = top_players(db, city)
        self.assertEqual(top[0]["name"], "@alice")
        self.assertIn("title", top[0])

        defender, _ = get_or_create_city(db, -1002, "Beta Chat")
        war, war_text = start_war(db, city, defender.invite_code)
        self.assertIsNotNone(war)
        self.assertEqual(war.status, "finished")
        self.assertTrue(war_text)

    def test_v03_viral_features(self):
        db = make_session()
        city, _ = get_or_create_city(db, -2001, "Drama Chat")
        users = []
        for uid, username in [(1, "alice"), (2, "bob"), (3, "carol")]:
            player, _, _ = get_or_create_player(db, uid, username, username.title())
            join_city(db, city, player)
            users.append(player)

        drama = create_drama_event(db, city, force=True)
        self.assertIsNotNone(drama)
        self.assertIn("@", drama.text)

        drama.resolved_at = None
        election_blocked = create_mayor_election(db, city)
        self.assertIsNone(election_blocked)
        drama.resolved_at = drama.created_at
        db.flush()

        election = create_mayor_election(db, city)
        self.assertIsNotNone(election)
        vote_event(db, city, users[0], 1)
        vote_event(db, city, users[1], 1)
        text = resolve_event(db, city)
        self.assertIn("Новый мэр", text)

        quest_before = quest_payload(db, city)
        payload, quest_text = help_city_quest(db, city, users[0])
        self.assertGreaterEqual(payload["progress"], quest_before["progress"] + 1)
        self.assertTrue(quest_text)
        _, second_text = help_city_quest(db, city, users[0])
        self.assertIn("уже помогал", second_text)

        newspaper = build_newspaper(db, city)
        self.assertIn("city", newspaper)
        self.assertIn("quest", newspaper)
        self.assertIn("logs", newspaper)

    def test_founder_title_only_for_chat_owner(self):
        db = make_session()
        city, _ = get_or_create_city(db, -3001, "Owner Chat")
        owner, _, _ = get_or_create_player(db, 10, "owner", "Owner")
        guest, _, _ = get_or_create_player(db, 11, "guest", "Guest")

        guest_membership, _ = join_city(db, city, guest, is_chat_owner=False)
        self.assertIsNone(guest_membership.special_title)

        owner_membership, _ = join_city(db, city, owner, is_chat_owner=True)
        self.assertEqual(owner_membership.special_title, FOUNDER_TITLE)
        self.assertEqual(city.owner_telegram_user_id, owner.telegram_user_id)

        top = top_players(db, city)
        owner_row = next(item for item in top if item["telegram_user_id"] == owner.telegram_user_id)
        guest_row = next(item for item in top if item["telegram_user_id"] == guest.telegram_user_id)
        self.assertIn("Основатель", owner_row["title"])
        self.assertNotIn("Основатель", guest_row["title"])

    def test_v05_court_jail_buildings_and_profile(self):
        db = make_session()
        city, _ = get_or_create_city(db, -4001, "Court Chat")
        player, _, _ = get_or_create_player(db, 20, "judgebait", "Judge")
        join_city(db, city, player)

        city.treasury = 300
        ok, text, buildings = build_city_building(db, city, "shawarma")
        self.assertTrue(ok)
        self.assertIn("shawarma", buildings["owned"])
        self.assertLess(city.treasury, 300)

        profile_before = player_profile(db, city, player)
        self.assertEqual(profile_before["status"], "свободен")

        court = create_court_event(db, city, target=player, force=True)
        self.assertIsNotNone(court)
        self.assertIn("court:", court.event_key)
        vote_event(db, city, player, 2)
        result_text = resolve_event(db, city)
        self.assertIn("подвал", result_text)

        profile_after = player_profile(db, city, player)
        self.assertIn("подвал", profile_after["status"])
        self.assertGreaterEqual(profile_after["convictions"], 1)

        payload = building_payload(city)
        self.assertTrue(payload["items"])

    def test_v06_raids_trophies_officials_and_weekly(self):
        db = make_session()
        attacker, _ = get_or_create_city(db, -5001, "Attack Chat")
        defender, _ = get_or_create_city(db, -5002, "Defense Chat")

        owner, _, _ = get_or_create_player(db, 30, "owner", "Owner")
        judge, _, _ = get_or_create_player(db, 31, "judge", "Judge")
        join_city(db, attacker, owner, is_chat_owner=True)
        join_city(db, attacker, judge)
        join_city(db, defender, judge)

        ok, text = appoint_city_official(db, attacker, judge, "судья")
        self.assertTrue(ok)
        self.assertIn("Судья", text)
        officials = city_officials(db, attacker)
        self.assertEqual(officials[0]["name"], "@judge")

        war, challenge_text, target, created = create_raid_challenge(db, attacker, defender.invite_code)
        self.assertTrue(created)
        self.assertIsNotNone(war)
        self.assertEqual(target.id, defender.id)
        incoming = active_incoming_raids(db, defender)
        self.assertEqual(incoming[0]["id"], war.id)

        resolved, raid_text = resolve_raid_challenge(db, defender, war.id)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.status, "finished")
        self.assertTrue(raid_text)
        self.assertTrue(get_city_trophies(attacker) or get_city_trophies(defender))

        summary = weekly_summary(db, attacker)
        self.assertIn("city", summary)
        self.assertIn("top", summary)

    def test_v07_daily_shop_season_and_global_top(self):
        db = make_session()
        city, _ = get_or_create_city(db, -7001, "Season Chat")
        player, _, _ = get_or_create_player(db, 70, "daily", "Daily")
        join_city(db, city, player)

        ok, text, payload = collect_daily_reward(db, city, player)
        self.assertTrue(ok)
        self.assertIn("ежеднев", text.lower())
        self.assertTrue(daily_payload(player)["collected"])
        profile = player_profile(db, city, player)
        self.assertGreaterEqual(profile["level"], 1)
        self.assertIn("daily_streak", profile)

        city.treasury = 500
        ok, shop_text, shop = buy_shop_item(db, city, "festival")
        self.assertTrue(ok)
        self.assertIn("festival", shop["owned"])
        self.assertTrue(shop_payload(city)["items"])

        season = season_payload(city)
        self.assertEqual(season["number"], 1)
        rolled, roll_text, new_season = maybe_roll_season(db, city, force=True)
        self.assertTrue(rolled)
        self.assertIn("Сезон", roll_text)
        self.assertEqual(new_season["number"], 2)

        cities = top_cities(db, limit=3)
        self.assertTrue(cities)
        self.assertIn("population", cities[0])
        self.assertIn("rank", cities[0])


if __name__ == "__main__":
    unittest.main()
