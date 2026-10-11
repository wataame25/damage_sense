import math
import random
import unittest

import main
from main import Battle, Combatant, GameData, calc_damage, calc_stat, chain_mods, poke_round

DATA = GameData.load()


def row(name):
    return next(r for r in DATA.pokemon if r["name"] == name)


def move(name):
    return next(m for m in DATA.moves.values() if m["name"] == name)


class StatTest(unittest.TestCase):
    def test_champions_formula_matches_pokedb(self):
        # champs.pokedb.tokyo のニンフィア（HP種族値95）最大実数値 202
        self.assertEqual(calc_stat(95, 32, is_hp=True), 202)
        self.assertEqual(calc_stat(95, 0, is_hp=True), 170)
        # こうげき種族値130・32振り・性格↑ → floor(182*1.1)=200
        self.assertEqual(calc_stat(130, 32, 1.1), 200)

    def test_nature_up_and_down_match_pokedb(self):
        # ガブリアス すばやさ（種族値102）: 最大+ 169 / 最大 154 / 最小 122 / 最小- 109
        self.assertEqual([calc_stat(102, 32, 1.1), calc_stat(102, 32), calc_stat(102, 0), calc_stat(102, 0, 0.9)],
                         [169, 154, 122, 109])


class RoundingTest(unittest.TestCase):
    def test_poke_round(self):
        self.assertEqual(poke_round(10.5), 10)   # 五捨
        self.assertEqual(poke_round(10.51), 11)  # 五超入

    def test_chain(self):
        self.assertEqual(chain_mods([]), 4096)
        self.assertEqual(chain_mods([6144]), 6144)
        self.assertEqual(chain_mods([4915, 5325]), 6390)


class DamageTest(unittest.TestCase):
    def test_plain_hit_matches_user_formula(self):
        """ガブリアス じしん → カバルドン（補正はタイプ一致のみ）を手計算と照合"""
        atk = Combatant(row("ガブリアス"), ability="さめはだ", points={"attack": 32})
        dfn = Combatant(row("カバルドン"), ability="すなのちから", points={"hp": 0, "defense": 0})
        res = calc_damage(DATA, atk, dfn, move("じしん"), Battle(None, None))
        a = 130 + 20 + 32           # 182
        d = 118 + 20                # 138
        base = math.floor(math.floor(50 * 2 / 5 + 2) * 100 * a / d)
        base = math.floor(base / 50) + 2
        expected = [poke_round(math.floor(base * r / 100) * 1.5) for r in range(85, 101)]
        self.assertEqual(res.damages, expected)
        self.assertEqual(res.hp, 108 + 75)

    def test_immunity_and_mold_breaker(self):
        atk = Combatant(row("ガブリアス"), ability="さめはだ")
        dfn = Combatant(row("ヒートロトム"), ability="ふゆう")
        self.assertIsNone(calc_damage(DATA, atk, dfn, move("じしん"), Battle(None, None)))
        atk.ability = "かたやぶり"
        self.assertIsNotNone(calc_damage(DATA, atk, dfn, move("じしん"), Battle(None, None)))

    def test_sun_boosts_fire(self):
        atk = Combatant(row("メガリザードンＹ"), ability="ひでり")
        dfn = Combatant(row("ハッサム"), ability="テクニシャン")
        none = calc_damage(DATA, atk, dfn, move("かえんほうしゃ"), Battle(None, None))
        sun = calc_damage(DATA, atk, dfn, move("かえんほうしゃ"), Battle("sunny", None))
        self.assertGreater(sun.min_damage, none.min_damage * 1.4)

    def test_psyshock_uses_target_defense(self):
        atk = Combatant(row("マフォクシー"), ability="もうか", points={"sp_attack": 32})
        dfn = Combatant(row("ドヒドイデ"), ability="さいせいりょく", points={"defense": 32, "sp_defense": 0})
        res = calc_damage(DATA, atk, dfn, move("サイコショック"), Battle(None, None))
        self.assertEqual(res.defense_key, "defense")
        dfn.points = {"defense": 0, "sp_defense": 32}
        self.assertGreater(calc_damage(DATA, atk, dfn, move("サイコショック"), Battle(None, None)).min_damage, res.min_damage)

    def test_multiscale_halves(self):
        atk = Combatant(row("マンムー"), ability="どんかん")
        dfn = Combatant(row("カイリュー"), ability="せいしんりょく")
        full = calc_damage(DATA, atk, dfn, move("つららおとし"), Battle(None, None))
        dfn.ability = "マルチスケイル"
        half = calc_damage(DATA, atk, dfn, move("つららおとし"), Battle(None, None))
        self.assertAlmostEqual(half.max_damage, full.max_damage / 2, delta=1)


class ItemTest(unittest.TestCase):
    def test_item_multiplier_applied_to_matching_type(self):
        item = next(i for i in DATA.items.values() if i["name"] == "くろいメガネ")
        base = Combatant(row("ドドゲザン"), ability="そうだいしょう")
        plain = calc_damage(DATA, base, Combatant(row("ゲンガー"), ability="のろわれボディ"),
                            move("ドゲザン"), Battle(None, None))
        for mult in (1.2, 1.3):
            atk = Combatant(row("ドドゲザン"), ability="そうだいしょう", item=item, item_multiplier=mult)
            res = calc_damage(DATA, atk, Combatant(row("ゲンガー"), ability="のろわれボディ"),
                              move("ドゲザン"), Battle(None, None))
            self.assertAlmostEqual(res.max_damage / plain.max_damage, mult, delta=0.03)
        # タイプ不一致の技には掛からない
        atk = Combatant(row("ドドゲザン"), ability="そうだいしょう", item=item, item_multiplier=1.3)
        dfn = Combatant(row("ゲンガー"), ability="のろわれボディ")
        self.assertEqual(calc_damage(DATA, atk, dfn, move("アイアンヘッド"), Battle(None, None)).damages,
                         calc_damage(DATA, base, dfn, move("アイアンヘッド"), Battle(None, None)).damages)

    def test_items_only_on_non_mega_with_random_multiplier(self):
        rng = random.Random(1)
        seen = set()
        for _ in range(3000):
            q = main.generate_question(DATA, rng)
            a = q.attacker
            if a.row["is_mega"]:
                self.assertIsNone(a.item)
            if a.item:
                self.assertGreaterEqual(a.item["multiplier"], 1.2)
                seen.add(a.item_multiplier)
        self.assertEqual(seen, {1.2, 1.3})


class SpreadNatureTest(unittest.TestCase):
    def test_choices_come_from_usage_over_threshold(self):
        rng = random.Random(3)
        for _ in range(1000):
            q = main.generate_question(DATA, rng)
            for c in (q.attacker, q.defender):
                groups = c.row["stat_point_usage"]
                self.assertTrue(all(g["usage_rate"] >= 10 for g in groups))
                spreads = [s["points"] for g in groups for s in g["spreads"]]
                self.assertIn(c.points, spreads)
                nat = next(n for n in c.row["nature_usage"] if n["name"] == c.nature_name)
                self.assertGreaterEqual(nat["usage_rate"], 10)
                if nat["down"]:
                    self.assertEqual(c.nature[nat["down"]], 0.9)
                    others = [n for n in c.row["nature_usage"]
                              if not (n["down"] and c.points[n["down"]] >= main.NATURE_CONFLICT_POINTS)]
                    if others:
                        self.assertLess(c.points[nat["down"]], main.NATURE_CONFLICT_POINTS)
            if q.attacker.item:
                cand = next(x for x in q.attacker.row["item_candidates"] if x["item_id"] == q.attacker.item["id"])
                self.assertGreaterEqual(cand["usage_rate"], 10)


class GeneratorTest(unittest.TestCase):
    def test_bulk_generation_respects_rules(self):
        rng = random.Random(0)
        for _ in range(500):
            q = main.generate_question(DATA, rng)
            self.assertLessEqual(q.result.min_percent, main.MAX_MIN_PERCENT)
            self.assertFalse(q.attacker.row["is_defensive_only"])
            self.assertNotEqual(q.attacker.row["form_selection"], "excluded")
            self.assertNotEqual(q.defender.row["form_selection"], "excluded")
            if q.attacker.row["is_mega"]:
                self.assertIsNone(q.attacker.item)
            self.assertNotIn(q.attacker.row["name"], ("ラグラージ", "リザードン", "メガガブリアス"))


if __name__ == "__main__":
    unittest.main()
