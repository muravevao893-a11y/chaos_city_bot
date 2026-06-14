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
    create_city_alliance,
    city_alliances,
    register_city_referral,
    admin_stats,
    black_market_payload,
    buy_black_market_item,
    create_duel_challenge,
    create_rumor_event,
    resolve_duel,
    rename_city,
    city_action_cooldown,
    vote_event,
    work,
    faction_payload,
    join_faction,
    inventory_payload,
    buy_item,
    use_item,
    steal_treasury,
    create_revolt_event,
    city_history_payload,
    attempt_escape,
    achievement_payload,
    daily_summary_payload,
    set_city_activity_mode,
    activity_mode_payload,
    auto_event_due,
    create_launch_event,
    city_launch_payload,
    reset_city_progress,
    raid_score_breakdown,
    EARLY_CITY_TROPHY,
    should_send_daily_summary,
    FOUNDER_TITLE,
    secret_role_payload,
    mission_payload,
    owner_stats_payload,
    ai_context_payload,
    ai_usage_allowed,
    register_ai_usage,
    stars_products_payload,
    owner_center_payload,
    city_store_payload,
    growth_analytics_payload,
    retention_payload,
    payments_analytics_payload,
    dead_chats_payload,
    promo_pack_payload,
    weekly_digest_payload,
    use_city_store_item,
    admin_errors_payload,
    admin_error_payload,
    admin_clear_errors,
    button_rate_limited,
    city_stage_payload,
    daily_action_limit_reached,
    error_count,
    log_error,
    production_audit_payload,
    EARLY_1000_CITY_TROPHY,
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

    def test_v08_referrals_alliances_and_admin_stats(self):
        db = make_session()
        referrer, _ = get_or_create_city(db, -8001, "Referrer Chat")
        invited, _ = get_or_create_city(db, -8002, "Invited Chat")
        third, _ = get_or_create_city(db, -8003, "Alliance Chat")

        ok, text = register_city_referral(db, invited, "city_" + referrer.invite_code)
        self.assertTrue(ok)
        self.assertIn("Бонус", text)
        self.assertGreaterEqual(referrer.treasury, 145)

        ok_again, text_again = register_city_referral(db, invited, referrer.invite_code)
        self.assertFalse(ok_again)
        self.assertIsNone(text_again)

        ok, ally_text, target = create_city_alliance(db, invited, third.invite_code)
        self.assertTrue(ok)
        self.assertIsNotNone(target)
        self.assertIn("союз", ally_text.lower())
        alliances = city_alliances(db, invited)
        self.assertEqual(len(alliances), 1)
        self.assertEqual(alliances[0]["name"], third.name)

        top = top_cities(db, limit=5)
        self.assertIn("alliances_count", top[0])
        self.assertIn("referrals_count", top[0])
        self.assertIn("trophies_count", top[0])

        stats = admin_stats(db)
        self.assertGreaterEqual(stats["cities_total"], 3)
        self.assertEqual(stats["referrals_total"], 1)
        self.assertEqual(stats["alliances_total"], 1)

    def test_v09_duels_black_market_rumors_and_owner_tools(self):
        db = make_session()
        city, _ = get_or_create_city(db, -9001, "Market Chat")
        alice, _, _ = get_or_create_player(db, 91, "alice", "Alice")
        bob, _, _ = get_or_create_player(db, 92, "bob", "Bob")
        join_city(db, city, alice, is_chat_owner=True)
        join_city(db, city, bob)
        alice.coins = 200
        bob.coins = 200

        rumor = create_rumor_event(db, city, force=True)
        self.assertIsNotNone(rumor)
        self.assertEqual(rumor.event_key, "rumor")
        allowed, left = city_action_cooldown(db, city, "rumor", 30)
        self.assertFalse(allowed)
        self.assertGreaterEqual(left, 1)

        payload = black_market_payload(city)
        self.assertTrue(payload["items"])
        ok, text, _payload, event = buy_black_market_item(db, city, alice, "fake_rep")
        self.assertTrue(ok)
        self.assertIn("репутац", text.lower())
        self.assertIsNone(event)

        duel, duel_text = create_duel_challenge(db, city, alice, bob, 25)
        self.assertIsNotNone(duel)
        self.assertIn("дуэль", duel_text.lower())
        resolved, result = resolve_duel(db, city, duel.id, bob)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.status, "finished")
        self.assertTrue(result.winner)

        ok, rename_text = rename_city(db, city, "Новый Район")
        self.assertTrue(ok)
        self.assertIn("Новый Район", rename_text)
        self.assertEqual(city.name, "Новый Район")

    def test_v10_factions_items_revolt_steal_history(self):
        db = make_session()
        city, _ = get_or_create_city(db, -10001, "Faction Chat")
        alice, _, _ = get_or_create_player(db, 101, "alice", "Alice")
        bob, _, _ = get_or_create_player(db, 102, "bob", "Bob")
        join_city(db, city, alice)
        join_city(db, city, bob)
        alice.coins = 300
        bob.coins = 300
        city.treasury = 300

        ok, text, factions = join_faction(db, city, alice, "mafia")
        self.assertTrue(ok)
        self.assertIn("Мафия", text)
        self.assertTrue(any(item["count"] >= 1 for item in factions["factions"]))
        profile = player_profile(db, city, alice)
        self.assertIn("Мафия", profile["faction"])

        ok, item_text, inventory = buy_item(db, city, alice, "smoke")
        self.assertTrue(ok)
        self.assertTrue(inventory["items"])
        ok, use_text, inventory_after = use_item(db, city, alice, "smoke")
        self.assertTrue(ok)
        self.assertIn("задымил", use_text)

        ok, steal_text = steal_treasury(db, city, alice)
        self.assertTrue(steal_text)
        self.assertIn("казн", steal_text.lower())

        event, revolt_text = create_revolt_event(db, city, bob, force=True)
        self.assertIsNotNone(event)
        self.assertEqual(event.event_key, "revolt")
        vote_event(db, city, alice, 1)
        vote_event(db, city, bob, 1)
        resolved = resolve_event(db, city)
        self.assertIn("Бунт", resolved)

        history = city_history_payload(city)
        self.assertTrue(history["items"])

        # escape path should not crash whether theft jailed the player or not
        ok, escape_text, _ = attempt_escape(db, city, alice)
        self.assertTrue(escape_text)


    def test_v11_achievements_daily_summary_and_activity_modes(self):
        db = make_session()
        city, _ = get_or_create_city(db, -11001, "Retention Chat")
        owner, _, _ = get_or_create_player(db, 111, "owner", "Owner")
        player, _, _ = get_or_create_player(db, 112, "worker", "Worker")
        join_city(db, city, owner, is_chat_owner=True)
        join_city(db, city, player)
        player.coins = 120
        work(db, city, player, cooldown_hours=0)
        achievements = achievement_payload(db, city, player)
        self.assertGreaterEqual(achievements["owned_count"], 2)
        self.assertTrue(achievements["items"])

        ok, text, mode = set_city_activity_mode(db, city, "chaos")
        self.assertTrue(ok)
        self.assertIn("Хаос", text)
        self.assertEqual(activity_mode_payload(city)["key"], "chaos")
        self.assertTrue(auto_event_due(city))

        summary = daily_summary_payload(db, city)
        self.assertIn("city", summary)
        self.assertIn("top", summary)
        self.assertTrue(summary["logs"])
        self.assertFalse(should_send_daily_summary(city))

    def test_v12_launch_reset_early_trophy_and_better_raids(self):
        db = make_session()
        city, created = get_or_create_city(db, -12001, "Launch Chat")
        self.assertTrue(created)
        self.assertIn(EARLY_CITY_TROPHY, get_city_trophies(city))

        payload = city_launch_payload(db, city)
        self.assertIn("city", payload)
        self.assertEqual(payload["early_trophy"], EARLY_CITY_TROPHY)

        event = create_launch_event(db, city)
        self.assertIsNotNone(event)
        self.assertEqual(event.event_key, "launch_first_event")
        self.assertIsNone(create_launch_event(db, city))

        attacker, _ = get_or_create_city(db, -12002, "Raiders")
        defender, _ = get_or_create_city(db, -12003, "Defenders")
        alice, _, _ = get_or_create_player(db, 1201, "alice", "Alice")
        bob, _, _ = get_or_create_player(db, 1202, "bob", "Bob")
        join_city(db, attacker, alice)
        join_city(db, defender, bob)
        attacker.treasury = 400
        defender.treasury = 400
        parts = raid_score_breakdown(db, attacker)
        self.assertIn("total", parts)
        self.assertGreater(parts["total"], 0)
        war, _text, _target, created = create_raid_challenge(db, attacker, defender.invite_code)
        self.assertTrue(created)
        resolved, raid_text = resolve_raid_challenge(db, defender, war.id)
        self.assertIsNotNone(resolved)
        self.assertIn("Счёт", raid_text)
        self.assertTrue(get_city_trophies(attacker) or get_city_trophies(defender))

        city.treasury = 999
        city.level = 4
        ok, reset_text = reset_city_progress(db, city)
        self.assertTrue(ok)
        self.assertIn("сброшен", reset_text.lower())
        self.assertEqual(city.level, 1)
        self.assertEqual(city.treasury, 25)
        self.assertIn(EARLY_CITY_TROPHY, get_city_trophies(city))



    def test_v13_ai_secret_roles_missions_owner_stats_and_stars(self):
        db = make_session()
        city, _ = get_or_create_city(db, -13001, "AI Chat")
        owner, _, _ = get_or_create_player(db, 1301, "owner", "Owner")
        player, _, _ = get_or_create_player(db, 1302, "agent", "Agent")
        join_city(db, city, owner, is_chat_owner=True)
        join_city(db, city, player)

        role = secret_role_payload(db, city, player)
        self.assertIn("name", role)
        self.assertTrue(role["key"])

        mission = mission_payload(db, city, player, check=False)
        self.assertTrue(mission["active"])
        self.assertIn("name", mission)

        work(db, city, player, cooldown_hours=0)
        mission_checked = mission_payload(db, city, player, check=True)
        self.assertIn("completed", mission_checked)

        stats = owner_stats_payload(db, city)
        self.assertIn("active_24h", stats)
        self.assertIn("ai", stats)

        context = ai_context_payload(db, city, "тест")
        self.assertIn("city", context)
        allowed, used, limit = ai_usage_allowed(db, city)
        self.assertFalse(allowed)
        register_ai_usage(db, city, "test")
        self.assertTrue(stars_products_payload()["items"])



    def test_v17_owner_analytics_store_and_retention(self):
        db = make_session()
        city, _ = get_or_create_city(db, -1701, "Growth Chat")
        player, _, _ = get_or_create_player(db, 1701, "owner", "Owner")
        join_city(db, city, player, is_chat_owner=True)
        work(db, city, player, cooldown_hours=0)

        self.assertIn(EARLY_1000_CITY_TROPHY, get_city_trophies(city))
        owner = owner_center_payload(db, city)
        self.assertIn("store", owner)
        self.assertIn("referral", owner)

        store = city_store_payload(db, city)
        self.assertIn("premium", store)
        ok, text, _, _ = use_city_store_item(db, city, player, "ai_newspaper")
        self.assertFalse(ok)
        self.assertIn("AI-газет", text)

        self.assertGreaterEqual(growth_analytics_payload(db)["cities_total"], 1)
        self.assertGreaterEqual(retention_payload(db)["cities_total"], 1)
        self.assertIn("stars_total", payments_analytics_payload(db))
        self.assertIsInstance(dead_chats_payload(db), list)
        self.assertIn("text", promo_pack_payload(db, city))
        self.assertIn("actions", weekly_digest_payload(db, city))


    def test_v18_production_hardening(self):
        db = make_session()
        city, _ = get_or_create_city(db, -9001, "Prod Chat")
        player, _, _ = get_or_create_player(db, 9001, "prod", "Prod")
        join_city(db, city, player, is_chat_owner=True)

        stage = city_stage_payload(db, city)
        self.assertEqual(stage["key"], "new")

        limited, left = button_rate_limited(db, city.chat_id, player.telegram_user_id, "cb:test", seconds=5)
        self.assertFalse(limited)
        limited, left = button_rate_limited(db, city.chat_id, player.telegram_user_id, "cb:test", seconds=5)
        self.assertTrue(limited)
        self.assertGreaterEqual(left, 1)

        err = log_error(db, "test", RuntimeError("boom"), traceback_text="trace", chat_id=city.chat_id, user_id=player.telegram_user_id)
        self.assertGreater(err.id, 0)
        self.assertEqual(error_count(db, 24), 1)
        errors = admin_errors_payload(db, limit=5)
        self.assertEqual(errors[0]["type"], "RuntimeError")
        detail = admin_error_payload(db, err.id)
        self.assertIn("boom", detail["message"])

        audit = production_audit_payload(db, city)
        self.assertEqual(audit["stage"]["key"], "new")
        self.assertIn("auto_event_hours", audit)

        reached, count, limit = daily_action_limit_reached(db, city, "court")
        self.assertFalse(reached)
        self.assertGreaterEqual(limit, 1)

        cleared = admin_clear_errors(db, days=1)
        self.assertEqual(cleared, 0)



if __name__ == "__main__":
    unittest.main()
