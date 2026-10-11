"""web/src/engine.js（JS移植版）の計算結果が main.py と一致するかを照合する。
macOS 標準の JavaScriptCore (jsc) で実行する。jsc が無い環境ではスキップ。"""

import json
import random
import subprocess
import tempfile
import unittest
from pathlib import Path

import main
from build_web import ROOT, data_js

JSC = Path("/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc")

RUNNER = """
var data = DamageEngine.indexData(GAME_DATA);
var mismatches = [], checked = 0;
SCENARIOS.forEach(function (s, i) {
  function mk(c) {
    var x = new DamageEngine.Combatant(data.pokemon.find(function (r) { return r.id === c.id; }), c.ability);
    x.item = c.item ? data.items[c.item] : null;
    x.points = c.points; x.nature = c.nature; x.boosts = c.boosts;
    return x;
  }
  var atk = mk(s.attacker), dfn = mk(s.defender);
  s.expected.forEach(function (e) {
    var r = DamageEngine.calcDamage(data, atk, dfn, data.moves[e.move], s.battle);
    var got = r ? r.damages : null;
    checked++;
    if (JSON.stringify(got) !== JSON.stringify(e.damages)) mismatches.push({ scenario: i, move: e.move, got: got, expected: e.damages });
  });
});
print(JSON.stringify({ checked: checked, mismatches: mismatches.slice(0, 5), count: mismatches.length }));
"""


def combatant_json(c):
    return {"id": c.row["id"], "ability": c.ability, "item": c.item["id"] if c.item else None,
            "points": c.points, "nature": c.nature, "boosts": c.boosts}


@unittest.skipUnless(JSC.exists(), "jsc がありません")
class WebParityTest(unittest.TestCase):
    def test_js_engine_matches_python(self):
        data = main.GameData.load()
        rng = random.Random(42)
        scenarios = []
        for _ in range(400):
            q = main.generate_question(data, rng)
            # 天候・フィールドを全組み合わせでも試す
            battle = main.Battle(rng.choice([None, *main.WEATHER_BALL_TYPE]), rng.choice([None, *main.TERRAIN_PULSE_TYPE]))
            for b in (q.battle, battle):
                expected = []
                for mid in q.attacker.row["moves"]:
                    r = main.calc_damage(data, q.attacker, q.defender, data.moves[mid], b)
                    expected.append({"move": mid, "damages": r.damages if r else None})
                scenarios.append({"attacker": combatant_json(q.attacker), "defender": combatant_json(q.defender),
                                  "battle": {"weather": b.weather, "field": b.field}, "expected": expected})
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            for name, content in [("data.js", data_js()),
                                  ("engine.js", (ROOT / "web/src/engine.js").read_text(encoding="utf-8")),
                                  ("scenarios.js", "var SCENARIOS = " + json.dumps(scenarios, ensure_ascii=False) + ";"),
                                  ("runner.js", RUNNER)]:
                p = Path(tmp) / name
                p.write_text(content, encoding="utf-8")
                files.append(str(p))
            out = subprocess.run([str(JSC), *files], capture_output=True, text=True, check=True).stdout
        res = json.loads(out.strip().splitlines()[-1])
        self.assertGreater(res["checked"], 1000)
        self.assertEqual(res["count"], 0, res["mismatches"])

    def test_js_generator_runs(self):
        script = "var d = DamageEngine.indexData(GAME_DATA); var rng = DamageEngine.makeRng(7); var bad = 0;" \
                 "for (var i = 0; i < 2000; i++) { var q = DamageEngine.generateQuestion(d, rng);" \
                 " if (q.result.minPercent > 110 || q.attacker.row.is_defensive_only || (q.attacker.row.is_mega && q.attacker.item)" \
                 " || q.attacker.row.form_selection === 'excluded' || q.defender.row.form_selection === 'excluded') bad++; }" \
                 "print(bad);"
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            for name, content in [("data.js", data_js()), ("engine.js", (ROOT / "web/src/engine.js").read_text(encoding="utf-8")),
                                  ("run.js", script)]:
                p = Path(tmp) / name
                p.write_text(content, encoding="utf-8")
                files.append(str(p))
            out = subprocess.run([str(JSC), *files], capture_output=True, text=True, check=True).stdout
        self.assertEqual(out.strip(), "0")


if __name__ == "__main__":
    unittest.main()
