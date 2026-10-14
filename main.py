"""damage_sense: ポケモンのダメージ感覚トレーニング（メイン実行ファイル）

使い方:
    python3 main.py                 # 難易度を対話で選択
    python3 main.py --mode easy     # 簡単（4択）
    python3 main.py --mode normal   # 普通（最低乱数を入力、誤差5%以内で正解）
    python3 main.py --mode challenge  # チャレンジ（全10問、誤差の合計を記録）
    python3 main.py --seed 1        # 乱数シードを固定（再現用）

計算の前提（DESIGN.md「7. ダメージ計算」も参照）:
    - Lv50、Pokémon Champions の能力ポイント制（1項目最大32）
    - 防御側はHP満タン・状態異常なし、急所なし（必ず急所に当たる技は除く）
    - 補正値は4096分率で掛け、五捨五超入で丸める
"""

import argparse
import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
LEVEL = 50
MAX_MIN_PERCENT = 110      # 最低乱数がこれを超える問題は出題しない
ANSWER_CAP = 100           # 最低乱数が100を超える場合は100を入力する
NORMAL_TOLERANCE = 5       # 普通モードの正解判定（±%）
CHALLENGE_QUESTIONS = 10

# ---------------------------------------------------------------------------
# データ読み込み
# ---------------------------------------------------------------------------


def _load(name):
    with open(DATA_DIR / f"{name}.json", encoding="utf-8") as f:
        return json.load(f)


@dataclass
class GameData:
    pokemon: list
    moves: dict
    abilities: dict
    items: dict
    weather: dict
    field: dict
    ev_rules: dict

    @classmethod
    def load(cls):
        return cls(
            pokemon=_load("pokemon"),
            moves={m["id"]: m for m in _load("moves")},
            abilities={a["id"]: a for a in _load("abilities")},
            items={i["id"]: i for i in _load("items")},
            weather={w["id"]: w for w in _load("weather")},
            field={f["id"]: f for f in _load("field")},
            ev_rules=_load("ev_rules"),
        )


# ---------------------------------------------------------------------------
# タイプ相性
# ---------------------------------------------------------------------------

TYPES = ["ノーマル", "ほのお", "みず", "でんき", "くさ", "こおり", "かくとう", "どく", "じめん",
         "ひこう", "エスパー", "むし", "いわ", "ゴースト", "ドラゴン", "あく", "はがね", "フェアリー"]

# 攻撃タイプ -> {防御タイプ: 倍率}（等倍は省略）
TYPE_CHART = {
    "ノーマル": {"いわ": 0.5, "ゴースト": 0, "はがね": 0.5},
    "ほのお": {"ほのお": 0.5, "みず": 0.5, "くさ": 2, "こおり": 2, "むし": 2, "いわ": 0.5, "ドラゴン": 0.5, "はがね": 2},
    "みず": {"ほのお": 2, "みず": 0.5, "くさ": 0.5, "じめん": 2, "いわ": 2, "ドラゴン": 0.5},
    "でんき": {"みず": 2, "でんき": 0.5, "くさ": 0.5, "じめん": 0, "ひこう": 2, "ドラゴン": 0.5},
    "くさ": {"ほのお": 0.5, "みず": 2, "くさ": 0.5, "どく": 0.5, "じめん": 2, "ひこう": 0.5, "むし": 0.5,
             "いわ": 2, "ドラゴン": 0.5, "はがね": 0.5},
    "こおり": {"ほのお": 0.5, "みず": 0.5, "くさ": 2, "こおり": 0.5, "じめん": 2, "ひこう": 2, "ドラゴン": 2, "はがね": 0.5},
    "かくとう": {"ノーマル": 2, "こおり": 2, "どく": 0.5, "ひこう": 0.5, "エスパー": 0.5, "むし": 0.5, "いわ": 2,
               "ゴースト": 0, "あく": 2, "はがね": 2, "フェアリー": 0.5},
    "どく": {"くさ": 2, "どく": 0.5, "じめん": 0.5, "いわ": 0.5, "ゴースト": 0.5, "はがね": 0, "フェアリー": 2},
    "じめん": {"ほのお": 2, "でんき": 2, "くさ": 0.5, "どく": 2, "ひこう": 0, "むし": 0.5, "いわ": 2, "はがね": 2},
    "ひこう": {"でんき": 0.5, "くさ": 2, "かくとう": 2, "むし": 2, "いわ": 0.5, "はがね": 0.5},
    "エスパー": {"かくとう": 2, "どく": 2, "エスパー": 0.5, "あく": 0, "はがね": 0.5},
    "むし": {"ほのお": 0.5, "くさ": 2, "かくとう": 0.5, "どく": 0.5, "ひこう": 0.5, "エスパー": 2, "ゴースト": 0.5,
             "あく": 2, "はがね": 0.5, "フェアリー": 0.5},
    "いわ": {"ほのお": 2, "こおり": 2, "かくとう": 0.5, "じめん": 0.5, "ひこう": 2, "むし": 2, "はがね": 0.5},
    "ゴースト": {"ノーマル": 0, "エスパー": 2, "ゴースト": 2, "あく": 0.5},
    "ドラゴン": {"ドラゴン": 2, "はがね": 0.5, "フェアリー": 0},
    "あく": {"かくとう": 0.5, "エスパー": 2, "ゴースト": 2, "あく": 0.5, "フェアリー": 0.5},
    "はがね": {"ほのお": 0.5, "みず": 0.5, "でんき": 0.5, "こおり": 2, "いわ": 2, "はがね": 0.5, "フェアリー": 2},
    "フェアリー": {"ほのお": 0.5, "かくとう": 2, "どく": 0.5, "ドラゴン": 2, "あく": 2, "はがね": 0.5},
}


def type_effectiveness(move_type, defender_types, move_name=None):
    eff = 1.0
    for t in defender_types:
        m = TYPE_CHART[move_type].get(t, 1)
        if move_name == "フリーズドライ" and t == "みず":
            m = 2
        eff *= m
    return eff


# ---------------------------------------------------------------------------
# 技・特性の個別ルール（データだけでは表現できないもの）
# ---------------------------------------------------------------------------

# 出題対象外の技（威力が変動する／連続技／カウンター系／参照ステータスが特殊）
UNSUPPORTED_MOVES = {
    "ミラーコート", "メタルバースト", "くさむすび",          # 威力なし・相手依存
    "つららばり", "みずしゅりけん", "トリプルアクセル", "ダブルウイング", "スケイルショット",  # 連続技
    "ボディプレス", "イカサマ",                             # 攻撃側のこうげき/とくこう以外を参照
}
# パンチ・波動・音の技（champs.pokedb.tokyo の技タグに合わせる）
PUNCH_MOVES = {"れいとうパンチ", "かみなりパンチ", "ほのおのパンチ", "マッハパンチ", "バレットパンチ", "コメットパンチ",
               "ドレインパンチ", "でんこうそうげき"}
PULSE_MOVES = {"みずのはどう", "あくのはどう", "りゅうのはどう", "はどうだん", "だいちのはどう"}
SOUND_MOVES = {"ハイパーボイス", "うたかたのアリア", "むしのさざめき", "フレアソング", "みわくのボイス", "バークアウト"}
# 特殊技だが相手のぼうぎょで計算する技
TARGET_DEFENSE_SPECIAL_MOVES = {"サイコショック"}
RECOIL_MOVES = {"すてみタックル", "フレアドライブ", "ブレイブバード", "ウッドハンマー", "ウェーブタックル", "とびひざげり"}
ALWAYS_CRIT_MOVES = {"トリックフラワー"}
# 場に出たターンにしか使えない技。積み技を使った後（＝出たターンではない）には使えない
FIRST_TURN_MOVES = {"であいがしら", "ねこだまし"}
# README記載の「攻撃力を強化する技」。出題時にランダムで1回使用済みにできる
BOOST_MOVES = {"りゅうのまい", "つるぎのまい", "わるだくみ", "ちょうのまい"}

WEATHER_SETTERS = {"ひでり": "sunny", "あめふらし": "rain", "すなおこし": "sandstorm", "ゆきふらし": "snow"}
FIELD_SETTERS = {"エレキメイカー": "electric_terrain", "グラスメイカー": "grassy_terrain",
                 "サイコメイカー": "psychic_terrain", "ミストメイカー": "misty_terrain"}
WEATHER_BALL_TYPE = {"sunny": "ほのお", "rain": "みず", "sandstorm": "いわ", "snow": "こおり"}
TERRAIN_PULSE_TYPE = {"electric_terrain": "でんき", "grassy_terrain": "くさ",
                      "psychic_terrain": "エスパー", "misty_terrain": "フェアリー"}
# 防御側の特性が無効化する技タイプ（かたやぶりで貫通）
IMMUNITY_ABILITIES = {"ふゆう": "じめん", "ちくでん": "でんき", "ひらいしん": "でんき"}

P_BOOST_USED = 0.5
# 最終補正として掛かる持ち物（実機の4096分率）。それ以外の持ち物は威力補正として items.json の倍率で掛ける
FINAL_MOD_ITEMS = {"たつじんのおび": 4915, "いのちのたま": 5324}
USAGE_THRESHOLD = 10          # 採用率がこれ未満の性格・振り方・持ち物は選ばない
INVESTED_POINTS = 16          # これ以上振ったステータスを「特化側」とみなす（性格の選択に使う）


# ---------------------------------------------------------------------------
# 計算の基本部品
# ---------------------------------------------------------------------------


def poke_round(x):
    """五捨五超入（0.5ちょうどは切り捨て、0.5を超えたら切り上げ）"""
    f = math.floor(x)
    return f + 1 if x - f > 0.5 else f


def chain_mods(mods):
    """4096分率の補正値を連結する"""
    m = 4096
    for x in mods:
        m = (m * x + 2048) >> 12
    return m


def apply_mod(value, mod4096):
    return poke_round(value * mod4096 / 4096)


def to4096(multiplier):
    """倍率を4096分率に変換（1.2倍→4915、1.3倍→5325 など実機の値に合わせる）"""
    return {1.1: 4505, 1.2: 4915, 1.3: 5325, 1.5: 6144, 2.0: 8192, 0.5: 2048}.get(
        multiplier, round(multiplier * 4096))


def calc_stat(base, points, nature=1.0, is_hp=False):
    """Champions方式の実数値（Lv50）"""
    if is_hp:
        return base + 75 + points
    # 浮動小数の誤差を避けるため整数で計算（1.1倍→×11÷10、0.9倍→×9÷10）
    return (base + 20 + points) * round(nature * 10) // 10


def apply_rank(stat, stages):
    if stages >= 0:
        return math.floor(stat * (2 + stages) / 2)
    return math.floor(stat * 2 / (2 - stages))


# ---------------------------------------------------------------------------
# 出題状況
# ---------------------------------------------------------------------------


@dataclass
class Combatant:
    row: dict
    ability: str                     # 特性名
    item: dict | None = None         # items.jsonの1件（持ち物なしはNone）
    points: dict = field(default_factory=dict)   # 能力ポイント
    nature: dict = field(default_factory=dict)   # 性格補正 {stat: 1.1/0.9}
    nature_name: str | None = None   # 性格名（例: ようき）
    spread_label: str | None = None  # 振り方の名前（例: AS + h）
    boosts: dict = field(default_factory=dict)   # 能力ランク {stat: 段階}
    boost_move: str | None = None    # 使用済みにした強化技

    @property
    def name(self):
        return self.row["name"]

    @property
    def types(self):
        return self.row["types"]

    def stat(self, key):
        return calc_stat(self.row["base_stats"][key], self.points.get(key, 0),
                         self.nature.get(key, 1.0), is_hp=(key == "hp"))

    def is_grounded(self):
        return "ひこう" not in self.types and self.ability != "ふゆう"


@dataclass
class Battle:
    weather: str | None   # weather.jsonのid
    field: str | None     # field.jsonのid
    weather_note: str | None = None   # どのポケモンの特性で発生したか
    field_note: str | None = None


@dataclass
class DamageResult:
    move: dict
    move_type: str
    power: int
    damages: list          # 乱数0.85〜1.00の16通り
    hp: int
    effectiveness: float
    notes: list
    defense_key: str = "defense"   # 防御側の参照ステータス（サイコショックは特殊でもdefense）
    stab: int = 0                  # タイプ一致補正（4096分率。0は不一致）
    stab_label: str | None = None  # 画面表示用（例: タイプ一致（リベロ））

    @property
    def min_damage(self):
        return self.damages[0]

    @property
    def max_damage(self):
        return self.damages[-1]

    @property
    def min_percent(self):
        return self.min_damage / self.hp * 100

    @property
    def max_percent(self):
        return self.max_damage / self.hp * 100


# ---------------------------------------------------------------------------
# ダメージ計算
# ---------------------------------------------------------------------------


def calc_damage(data: GameData, atk: Combatant, dfn: Combatant, move: dict, battle: Battle):
    """1つの技について16通りのダメージを返す。技が出せない/無効の場合はNone"""
    name = move["name"]
    if move["category"] == "変化" or move["power"] is None or name in UNSUPPORTED_MOVES:
        return None
    if name == "ソーラービーム" and battle.weather != "sunny":
        return None  # はれ以外は溜めが必要なため出題対象外
    if name == "エレクトロビーム" and battle.weather != "rain":
        return None  # あめ以外は溜めが必要なため出題対象外
    if name == "でんこうそうげき" and "でんき" not in atk.types:
        return None

    notes = []
    mold_breaker = atk.ability == "かたやぶり"
    dfn_ability = None if mold_breaker else dfn.ability
    physical = move["category"] == "物理"
    move_type = move["type"]
    base_power = move["power"]

    # --- 技タイプ・基礎威力の変化 ---
    if name == "ウェザーボール" and battle.weather:
        move_type, base_power = WEATHER_BALL_TYPE[battle.weather], 100
    if name == "だいちのはどう" and battle.field and atk.is_grounded():
        move_type, base_power = TERRAIN_PULSE_TYPE[battle.field], 100
    if name == "ワイドフォース" and battle.field == "psychic_terrain" and atk.is_grounded():
        base_power = 120
    if name == "アシストパワー":
        base_power = 20 + 20 * sum(v for v in atk.boosts.values() if v > 0)
    skin_boost = False
    if move_type == "ノーマル" and atk.ability in ("スカイスキン", "フェアリースキン"):
        move_type = "ひこう" if atk.ability == "スカイスキン" else "フェアリー"
        skin_boost = True
    if atk.ability == "うるおいボイス" and name in SOUND_MOVES:
        move_type = "みず"

    # --- 無効判定 ---
    eff = type_effectiveness(move_type, dfn.types, name)
    if dfn_ability in IMMUNITY_ABILITIES and IMMUNITY_ABILITIES[dfn_ability] == move_type:
        eff = 0
    if eff == 0:
        return None

    # --- 威力補正 ---
    power_mods = []
    if skin_boost:
        power_mods.append(4915)
    if atk.ability == "テクニシャン" and base_power <= 60:
        power_mods.append(6144)
    if atk.ability == "てつのこぶし" and name in PUNCH_MOVES:
        power_mods.append(4915)
    if atk.ability == "メガランチャー" and name in PULSE_MOVES:
        power_mods.append(6144)
    if atk.ability == "かたいツメ" and move.get("makes_contact"):
        power_mods.append(5325)
    if atk.ability == "すてみ" and name in RECOIL_MOVES:
        power_mods.append(4915)
    if atk.ability == "すなのちから" and battle.weather == "sandstorm" and move_type in ("いわ", "じめん", "はがね"):
        power_mods.append(5325)
    if name == "はたきおとす" and not dfn.row["is_mega"]:
        power_mods.append(6144)  # 防御側は道具を持っている前提（メガストーンは落とせないので対象外）
        notes.append("はたきおとす：防御側が道具を持っている前提で威力1.5倍")
    if name == "アクロバット":
        notes.append("アクロバット：攻撃側が道具を持っている前提で威力2倍にしない")
    if atk.item and atk.item["name"] not in FINAL_MOD_ITEMS and item_applies(atk.item, move, move_type, physical, eff):
        power_mods.append(to4096(atk.item["multiplier"]))
    if battle.field:
        fd = data.field[battle.field]
        if atk.is_grounded() and move_type in fd["move_type_multiplier"]:
            power_mods.append(to4096(fd["move_type_multiplier"][move_type]))
        if dfn.is_grounded() and move_type in fd["defender_type_multiplier"]:
            if battle.field != "grassy_terrain" or name == "じしん":
                power_mods.append(to4096(fd["defender_type_multiplier"][move_type]))
    power = max(1, apply_mod(base_power, chain_mods(power_mods)))

    # --- 攻撃側のこうげき/とくこう ---
    a_key = "attack" if physical else "sp_attack"
    a_stat = atk.stat(a_key)
    a_stage = atk.boosts.get(a_key, 0)
    if name == "エレクトロビーム":
        a_stage = min(6, a_stage + (-1 if atk.ability == "あまのじゃく" else 1))
        notes.append("エレクトロビーム：攻撃前にとくこうが1段階上がる（あめのため溜めなしで攻撃）")
    if dfn_ability == "てんねん":
        a_stage = 0
    a_stat = apply_rank(a_stat, a_stage)
    atk_mods = []
    if atk.ability == "サンパワー" and battle.weather == "sunny" and not physical:
        atk_mods.append(6144)
    if dfn_ability == "あついしぼう" and move_type in ("ほのお", "こおり"):
        atk_mods.append(2048)
    a_stat = max(1, apply_mod(a_stat, chain_mods(atk_mods)))

    # --- 防御側のぼうぎょ/とくぼう ---
    d_key = "defense" if physical or name in TARGET_DEFENSE_SPECIAL_MOVES else "sp_defense"
    d_stat = dfn.stat(d_key)
    if atk.ability != "てんねん":
        d_stat = apply_rank(d_stat, dfn.boosts.get(d_key, 0))
    def_mods = []
    if battle.weather:
        wd = data.weather[battle.weather]
        for t, rule in wd["defender_stat_multiplier"].items():
            if t in dfn.types and rule["stat"] == d_key:
                def_mods.append(to4096(rule["multiplier"]))
    d_stat = max(1, apply_mod(d_stat, chain_mods(def_mods)))

    # --- 基本ダメージ（ユーザー指定の式） ---
    base = math.floor(LEVEL * 2 / 5 + 2)
    base = math.floor(base * power * a_stat / d_stat)
    base = math.floor(base / 50) + 2

    # --- 中略：天候・急所 ---
    if battle.weather:
        wmul = data.weather[battle.weather]["move_type_multiplier"].get(move_type)
        if wmul:
            base = apply_mod(base, to4096(wmul))
    if name in ALWAYS_CRIT_MOVES:
        base = apply_mod(base, 6144)
        notes.append(f"{name}：必ず急所（1.5倍）")

    # --- 後略：タイプ一致・相性・その他の最終補正 ---
    stab, stab_label = 0, None
    if move_type in atk.types:
        stab = 8192 if atk.ability == "てきおうりょく" else 6144
        stab_label = "タイプ一致（てきおうりょく）" if stab == 8192 else "タイプ一致"
    elif atk.ability in ("へんげんじざい", "リベロ"):
        stab, stab_label = 6144, f"タイプ一致（{atk.ability}：技と同じタイプに変化）"
    final_mods = []
    if dfn_ability == "マルチスケイル":
        final_mods.append(2048)  # HP満タン前提
    if dfn_ability == "はどうのぼうご" and move.get("makes_contact"):
        final_mods.append(2048)
    if atk.item and atk.item["name"] in FINAL_MOD_ITEMS and item_applies(atk.item, move, move_type, physical, eff):
        final_mods.append(FINAL_MOD_ITEMS[atk.item["name"]])
    final = chain_mods(final_mods)

    damages = []
    for r in range(85, 101):
        d = math.floor(base * r / 100)
        if stab:
            d = apply_mod(d, stab)
        d = math.floor(d * eff)
        d = apply_mod(d, final)
        damages.append(max(1, d))

    return DamageResult(move=move, move_type=move_type, power=power, damages=damages,
                        hp=dfn.stat("hp"), effectiveness=eff, notes=notes, defense_key=d_key,
                        stab=stab, stab_label=stab_label)


def item_applies(item, move, move_type, physical, eff):
    """持ち物の倍率がこの技に掛かるか（タイプ強化系は一致タイプのみ、たつじんのおびは効果バツグンのみ）"""
    rule = item["applies_to"]
    if item["name"] == "たつじんのおび" and eff <= 1:
        return False
    if rule["move_type"] and rule["move_type"] != move_type:
        return False
    if rule["move_category"] and rule["move_category"] != ("物理" if physical else "特殊"):
        return False
    if rule["move_id"] and rule["move_id"] != move["id"]:
        return False
    return True


# ---------------------------------------------------------------------------
# 出題
# ---------------------------------------------------------------------------


@dataclass
class Question:
    attacker: Combatant
    defender: Combatant
    battle: Battle
    result: DamageResult

    @property
    def answer(self):
        """プレイヤーが入力すべき値（最低乱数%、100超は100）"""
        return min(ANSWER_CAP, self.result.min_percent)


def species_key(row):
    return row["mega_of"] or row["id"]


def pick_form(rows, rng):
    """同一種族の行から出題形態を1つ選ぶ（メガ/メガZ/X・Yは通常からの分岐として扱う）"""
    fixed = [r for r in rows if r["form_selection"] == "fixed"]
    if fixed:
        return fixed[0]
    return rng.choice([r for r in rows if r["form_selection"] == "random"])


def pick_ability(data, row, rng):
    usage = row["ability_usage"]
    chosen = rng.choices(usage, weights=[u["usage_rate"] for u in usage])[0]
    return data.abilities[chosen["ability_id"]]["name"]


def pick_item(data, row, rng):
    """所持率10%超の火力アップ持ち物を、その所持率の確率で持たせる。
    メガポケモンには持たせない。1.1倍系（ハチマキ/メガネ）は持つ機会が少ないため対象外"""
    if row["is_mega"]:
        return None
    roll = rng.uniform(0, 100)
    acc = 0.0
    for cand in row.get("item_candidates", []):
        if data.items[cand["item_id"]]["multiplier"] < 1.2 or cand["usage_rate"] < USAGE_THRESHOLD:
            continue
        acc += cand["usage_rate"]
        if roll < acc:
            return data.items[cand["item_id"]]
    return None


def make_combatant(data, row, rng, role):
    c = Combatant(row=row, ability=pick_ability(data, row, rng))
    pick_spread_and_nature(row, rng, c)
    if role == "attacker":
        c.item = pick_item(data, row, rng)
        # 積み技は振り方に合うもの（AS振りならこうげきが上がる技）だけを使用済みにする
        stats = attacking_stats(c)
        boost_moves = [data.moves[m] for m in row["moves"] if data.moves[m]["name"] in BOOST_MOVES
                       and any(b["stat"] in stats for b in data.moves[m]["boosts_own_stat"])]
        if boost_moves and row.get("boost_move_used_flag_eligible") and rng.random() < P_BOOST_USED:
            bm = rng.choice(boost_moves)
            c.boost_move = bm["name"]
            sign = -1 if c.ability == "あまのじゃく" else 1
            for b in bm["boosts_own_stat"]:
                c.boosts[b["stat"]] = max(-6, min(6, c.boosts.get(b["stat"], 0) + sign * b["stages"]))
    return c


def pick_spread_and_nature(row, rng, c):
    """採用率10%以上の振り方・性格から、採用率で重み付けして選ぶ（攻撃側・防御側共通）"""
    groups = row["stat_point_usage"]
    group = rng.choices(groups, weights=[g["usage_rate"] for g in groups])[0]
    spread = rng.choices(group["spreads"], weights=[s["usage_rate"] for s in group["spreads"]])[0]
    c.points = dict(spread["points"])
    c.spread_label = spread["label"]
    natures = [n for n in row["nature_usage"] if nature_fits(n, c.points)] or row["nature_usage"]
    nature = rng.choices(natures, weights=[n["usage_rate"] for n in natures])[0]
    c.nature_name = nature["name"]
    c.nature = {}
    if nature["up"]:
        c.nature[nature["up"]] = 1.1
    if nature["down"]:
        c.nature[nature["down"]] = 0.9


def nature_fits(nature, points):
    """振り方に合う性格か：特化側（16ポイント以上振ったステータス）を上げ、特化側を下げない性格。
    例：AS振りならこうげき/すばやさ上昇、HB振りならぼうぎょ上昇。無補正の性格は選ばない"""
    invested = {k for k, v in points.items() if v >= INVESTED_POINTS and k != "hp"}
    return nature["up"] in invested and nature["down"] not in invested


def resolve_setter(atk, dfn, setters, rng):
    """天候/フィールドを発生させる特性の持ち主を決める。特性を持つポケモンがいなければ発生しない。
    両方が持つ場合は後から発動した方で上書きされる：
      1. メガシンカしたポケモン（メガシンカ時に特性が発動するため後になる）
      2. どちらもメガ／どちらも非メガなら、すばやさが遅いポケモン
      3. 同速ならランダム
    戻り値: (発生するid, 説明) / 該当なしは (None, None)"""
    cands = [c for c in (atk, dfn) if c.ability in setters]
    if not cands:
        return None, None
    if len(cands) == 1:
        c = cands[0]
        return setters[c.ability], f"{c.name}の{c.ability}"
    a, d = cands
    if a.row["is_mega"] != d.row["is_mega"]:
        win, lose = (a, d) if a.row["is_mega"] else (d, a)
        why = f"メガシンカした{win.name}が後から発動して{lose.name}の{lose.ability}を上書き"
    elif a.stat("speed") != d.stat("speed"):
        win, lose = sorted(cands, key=lambda c: c.stat("speed"))
        why = (f"すばやさが遅い{win.name}（{win.stat('speed')}）が後から発動して"
               f"{lose.name}（{lose.stat('speed')}）の{lose.ability}を上書き")
    else:
        win, lose = rng.sample(cands, 2)
        why = f"同速（{win.stat('speed')}）のためランダムで{win.name}が後から発動"
    return setters[win.ability], f"{win.name}の{win.ability}（{why}）"


def decide_battle(atk, dfn, rng):
    weather, weather_note = resolve_setter(atk, dfn, WEATHER_SETTERS, rng)
    fld, field_note = resolve_setter(atk, dfn, FIELD_SETTERS, rng)
    return Battle(weather=weather, field=fld, weather_note=weather_note, field_note=field_note)


def attacking_stats(c):
    """振り方から攻撃側の戦い方を決める：こうげき/とくこうのうち16ポイント以上振った方。
    両方振っている・どちらも振っていない場合は両方"""
    inv = {k for k in ("attack", "sp_attack") if c.points.get(k, 0) >= INVESTED_POINTS}
    return inv if len(inv) == 1 else {"attack", "sp_attack"}


def best_move(data, atk, dfn, battle):
    """防御側に最もダメージを与えられる技（最高乱数→最低乱数の順で比較）。
    振り方に合う分類の技だけを使う（AS振りなら物理技、CS振りなら特殊技）"""
    cats = {"物理" if k == "attack" else "特殊" for k in attacking_stats(atk)}
    results = [calc_damage(data, atk, dfn, data.moves[m], battle) for m in atk.row["moves"]
               if data.moves[m]["category"] in cats
               and not (atk.boost_move and data.moves[m]["name"] in FIRST_TURN_MOVES)]
    results = [r for r in results if r]
    if not results:
        return None
    return max(results, key=lambda r: (r.max_damage, r.min_damage))


def generate_question(data, rng, max_tries=1000):
    species = {}
    for row in data.pokemon:
        species.setdefault(species_key(row), []).append(row)
    keys = list(species)
    for _ in range(max_tries):
        a_key, d_key = rng.sample(keys, 2)
        a_row = pick_form(species[a_key], rng)
        if a_row["is_defensive_only"]:
            continue
        d_row = pick_form(species[d_key], rng)
        atk = make_combatant(data, a_row, rng, "attacker")
        dfn = make_combatant(data, d_row, rng, "defender")
        battle = decide_battle(atk, dfn, rng)
        result = best_move(data, atk, dfn, battle)
        if result is None or result.min_percent > MAX_MIN_PERCENT:
            continue
        return Question(atk, dfn, battle, result)
    raise RuntimeError("条件を満たす問題を生成できませんでした")


# ---------------------------------------------------------------------------
# 表示
# ---------------------------------------------------------------------------

STAT_LABEL = {"hp": "HP", "attack": "こうげき", "defense": "ぼうぎょ",
              "sp_attack": "とくこう", "sp_defense": "とくぼう", "speed": "すばやさ"}


def _stat_line(c, key):
    n = c.nature.get(key, 1.0)
    nat = "（性格↑）" if n > 1 else "（性格↓）" if n < 1 else ""
    return f"{STAT_LABEL[key]} {c.stat(key)}（種族値{c.row['base_stats'][key]}・{c.points.get(key, 0)}振り{nat}）"


def format_item(c):
    if not c.item:
        return "なし（火力アップ系以外）"
    rule = c.item["applies_to"]
    if c.item["name"] == "たつじんのおび":
        target = "効果バツグンの技"
    elif rule["move_type"]:
        target = f"{rule['move_type']}技"
    elif rule["move_category"]:
        target = f"{rule['move_category']}技"
    else:
        target = "全ての攻撃技"
    return f"{c.item['name']}（{target}×{c.item['multiplier']:g}）"


def format_question(data, q: Question):
    a, d, r = q.attacker, q.defender, q.result
    physical = r.move["category"] == "物理"
    a_key = "attack" if physical else "sp_attack"
    d_key = r.defense_key
    move_desc = f"{r.move['name']}（{r.move_type}・{r.move['category']}・威力{r.move['power']}）"
    lines = [
        f"【攻撃側】{a.name}（{'/'.join(a.types)}）",
        f"  特性: {a.ability}　持ち物: {format_item(a)}",
        f"  性格: {a.nature_name}　振り方: {a.spread_label}",
        f"  {_stat_line(a, a_key)}",
    ]
    if a.boost_move:
        stages = a.boosts.get(a_key, 0)
        lines.append(f"  ※{a.boost_move}を1回使用済み（{STAT_LABEL[a_key]}ランク{stages:+d}）")
    lines += [
        f"【防御側】{d.name}（{'/'.join(d.types)}）",
        f"  特性: {d.ability}",
        f"  性格: {d.nature_name}　振り方: {d.spread_label}",
        f"  {_stat_line(d, 'hp')}",
        f"  {_stat_line(d, d_key)}",
        f"【天候】{data.weather[q.battle.weather]['name'] + '：' + q.battle.weather_note if q.battle.weather else 'なし'}",
        f"【フィールド】{data.field[q.battle.field]['name'] + '：' + q.battle.field_note if q.battle.field else 'なし'}",
        f"【使用技】{move_desc}",
    ]
    return "\n".join(lines)


def stat_formula(c, key):
    """実数値の計算式（能力補正＝性格込み）"""
    b, p, n = c.row["base_stats"][key], c.points.get(key, 0), c.nature.get(key, 1.0)
    if key == "hp":
        return f"{b} + 75 + {p} = {c.stat(key)}"
    if n == 1.0:
        return f"{b} + 20 + {p} = {c.stat(key)}"
    return f"floor(({b} + 20 + {p}) × {n:g}) = {c.stat(key)}（能力補正{'↑' if n > 1 else '↓'}）"


def format_answer(q: Question):
    r = q.result
    a_key = "attack" if r.move["category"] == "物理" else "sp_attack"
    lines = [
        f"ダメージ: {r.min_damage}〜{r.max_damage} / HP {r.hp}",
        f"割合: {r.min_percent:.1f}%〜{r.max_percent:.1f}%（相性 ×{r.effectiveness:g}"
        f"{'、' + r.stab_label + ' ×' + format(r.stab / 4096, 'g') if r.stab else ''}）",
        f"  {STAT_LABEL[a_key]}: {stat_formula(q.attacker, a_key)}",
        f"  {STAT_LABEL[r.defense_key]}: {stat_formula(q.defender, r.defense_key)}",
        f"  HP: {stat_formula(q.defender, 'hp')}",
    ]
    lines += [f"  ※{n}" for n in r.notes]
    return "\n".join(lines)


def easy_choices(q: Question, rng):
    """4択：正解の割合レンジ＋ずらしたダミー3つ"""
    lo, hi = q.result.min_percent, q.result.max_percent
    factors = rng.sample([0.5, 0.67, 0.8, 1.25, 1.5, 2.0], 3)
    options = [(lo, hi, True)] + [(lo * f, hi * f, False) for f in factors]
    rng.shuffle(options)
    return options


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def ask_number(prompt):
    while True:
        s = input(prompt).strip()
        try:
            return float(s)
        except ValueError:
            print("数値を入力してください")


def ask_continue():
    return input("次の問題に進みますか？ [Y/n]: ").strip().lower() not in ("n", "no", "q")


def run_easy(data, rng):
    while True:
        q = generate_question(data, rng)
        print("\n" + format_question(data, q))
        options = easy_choices(q, rng)
        for i, (lo, hi, _) in enumerate(options, 1):
            print(f"  {i}. {lo:.1f}%〜{hi:.1f}%")
        while True:
            pick = ask_number("番号を選んでください: ")
            if 1 <= pick <= 4:
                break
        print("正解！" if options[int(pick) - 1][2] else "不正解")
        print(format_answer(q))
        if not ask_continue():
            return


def run_normal(data, rng):
    while True:
        q = generate_question(data, rng)
        print("\n" + format_question(data, q))
        guess = ask_number("最低乱数のダメージ割合（%、100超なら100）: ")
        err = abs(guess - q.answer)
        print(f"{'正解！' if err <= NORMAL_TOLERANCE else '不正解'}（正解 {q.answer:.1f}%、誤差 {err:.1f}%）")
        print(format_answer(q))
        if not ask_continue():
            return


def run_challenge(data, rng):
    total = 0.0
    for i in range(1, CHALLENGE_QUESTIONS + 1):
        q = generate_question(data, rng)
        print(f"\n===== 第{i}問 / {CHALLENGE_QUESTIONS} =====")
        print(format_question(data, q))
        guess = ask_number("最低乱数のダメージ割合（%、100超なら100）: ")
        err = abs(guess - q.answer)
        total += err
        print(f"正解 {q.answer:.1f}%、誤差 {err:.1f}%（累計 {total:.1f}%）")
        print(format_answer(q))
    print(f"\nチャレンジ終了！ 誤差の合計: {total:.1f}%")


def main():
    parser = argparse.ArgumentParser(description="damage_sense: ダメージ感覚トレーニング")
    parser.add_argument("--mode", choices=["easy", "normal", "challenge"])
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    data = GameData.load()
    rng = random.Random(args.seed)
    mode = args.mode
    if not mode:
        sel = input("難易度を選択 1:簡単 2:普通 3:チャレンジ > ").strip()
        mode = {"1": "easy", "2": "normal", "3": "challenge"}.get(sel, "easy")
    {"easy": run_easy, "normal": run_normal, "challenge": run_challenge}[mode](data, rng)


if __name__ == "__main__":
    main()
