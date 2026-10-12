"""champs.pokedb.tokyo から指定シーズンの使用率データを取得し、data/pokemon.json と
data/usage_snapshot.json を作り直す。技・特性マスタに無いものは moves.json / abilities.json に追加する。

    python3 tools/build_usage_data.py --season 6          # シーズンM-6（シングル）
    python3 tools/build_usage_data.py --season 6 --refetch  # キャッシュを使わず取り直す

取得したページは .cache/pokedb/ に保存し、2回目以降はそれを使う。
"""

import argparse
import datetime
import html
import json
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = ROOT / ".cache" / "pokedb"
BASE_URL = "https://champs.pokedb.tokyo"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

TOP_N = 50
USAGE_THRESHOLD = 10          # 性格・振り方・持ち物はこれ未満の採用率を除外
ATTACK_MOVES = 5              # 採用率上位の攻撃技をいくつ持つか
BOOST_MOVES = {"りゅうのまい", "つるぎのまい", "わるだくみ", "ちょうのまい"}
DEFENSIVE_ONLY = {"アーマーガア", "ドヒドイデ", "ピクシー", "メガピクシー"}   # README指定。攻撃側に選ばない
MEGA_FIXED_RATE = 60          # メガストーン所持率がこれを超えたらメガ固定
MEGA_RANDOM_RATE = 30         # これを超えたら通常/メガをランダム
FORCE_NORMAL = set()          # 通常形態に固定する種族（メガ率に関係なく）
FORCE_MEGA = {"カイリュー"}    # メガ形態に固定（指示による。通常カイリューは環境にいないため）
# 通常形態では使われない振り方（メガ形態の型が混ざって集計されているもの）。{ポケモン名: 除外する攻撃ステータス}
# ガブリアスのCS振りはメガガブリアスＺの型、ラグラージのAS振りはメガラグラージの型（通常ラグラージはHB）
NORMAL_FORM_EXCLUDE = {"ガブリアス": "sp_attack", "ラグラージ": "attack"}
INVESTED_POINTS = 16          # これ以上振ったステータスを「特化側」とみなす
STAT_LETTER = {"H": "hp", "A": "attack", "B": "defense", "C": "sp_attack", "D": "sp_defense", "S": "speed"}
STAT_JP = {"攻撃": "attack", "防御": "defense", "特攻": "sp_attack", "特防": "sp_defense", "素早さ": "speed"}


# ---------------------------------------------------------------- 取得

def fetch(url, path, refetch):
    if path.exists() and not refetch:
        return path.read_text(encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["curl", "-sfL", "-A", UA, "-o", str(path), url], check=True)
    time.sleep(0.7)
    return path.read_text(encoding="utf-8")


def parse_list(page):
    pat = re.compile(r'<a href="/pokemon/show/([^"?]+)[^"]*"[^>]*class="list-pokemon[^"]*">\s*'
                     r'<div class="pokemon-rank[^"]*">\s*([0-9]+)\s*</div>', re.S)
    ranking = [(int(m.group(2)), m.group(1)) for m in pat.finditer(page)]
    title = re.search(r"<title>(.*?)</title>", page).group(1)
    return [x for x in ranking if x[0] <= TOP_N], title


# ---------------------------------------------------------------- 個別ページの解析

def xdata(page, name):
    m = re.search(r'x-data="' + name + r'\((\{.*?\})\)"\s', page, re.S)
    return json.loads(html.unescape(m.group(1)))


def visible_text(page):
    s = re.sub(r"<script.*?</script>", "", page, flags=re.S)
    s = re.sub(r'x-data="[^"]*"', "", s)
    return [x.strip() for x in re.sub(r"<[^>]+>", "\n", s).split("\n") if x.strip()]


def parse_abilities(page):
    t = visible_text(page)
    res = []
    for i in range(len(t) - 2):
        if t[i] == "特性" and t[i + 1] == "1":
            j = i + 1
            while j + 2 < len(t) and t[j].isdigit():
                res.append((t[j + 1], float(t[j + 2].rstrip("%"))))
                j += 4 if j + 3 < len(t) and t[j + 3].endswith("%") else 3
            break
    return res


def parse_items(page):
    i = page.index("<h3>持ち物</h3>")
    j = page.index("</ul>", page.index('<ul class="usage-list"', i))
    return [(n, float(r)) for n, r in re.findall(
        r'<span class="usage-name">\s*([^<]+?)\s*</span>\s*<span class="usage-rate[^"]*">([\d.]+)%', page[i:j])]


def parse_natures(page):
    i = page.index("<h3>能力補正</h3>")
    j = page.index("</ul>", page.index('<ul class="usage-list"', i))
    out = []
    for m in re.finditer(r'<span class="usage-name">\s*(\S+)\s*(?:<small[^>]*>(.*?)</small>)?\s*</span>\s*'
                         r'<span class="usage-rate[^"]*">([\d.]+)%', page[i:j], re.S):
        mods = m.group(2) or ""
        up, down = re.search(r"([HABCDS])↑", mods), re.search(r"([HABCDS])↓", mods)
        out.append({"name": m.group(1), "up": STAT_LETTER[up.group(1)] if up else None,
                    "down": STAT_LETTER[down.group(1)] if down else None, "usage_rate": float(m.group(3))})
    return out


def _chips(s):
    pts = {v: 0 for v in STAT_LETTER.values()}
    for lab, val in re.findall(r'spread__label">([HABCDS])</span>\s*<span class="pokemon-stat-spread__value[^"]*">(\d+)<', s):
        pts[STAT_LETTER[lab]] = int(val)
    return pts


def parse_spread_groups(page):
    i = page.index("x-show=\"statViewMode === 'aggregated'\"")
    j = page.index("x-show=\"statViewMode === 'raw'\"")
    groups = []
    for li in re.split(r'<li class="usage-list-item usage-list-item--stats"[^>]*>', page[i:j])[1:]:
        name = re.search(r'usage-name--stats">([^<]*)<', li).group(1).strip()
        rate = float(re.search(r'usage-rate[^"]*">([\d.]+)%', li).group(1))
        parts = li.split('<li class="pokemon-stat-spread__detail">')
        spreads = [{"label": re.search(r'detail-name">([^<]*)<', p).group(1).strip(),
                    "usage_rate": float(re.search(r'detail-rate[^"]*">([\d.]+)%', p).group(1)),
                    "points": _chips(p)} for p in parts[1:]]
        if not spreads:  # 1件だけのグループは詳細欄が無い
            spreads = [{"label": name, "usage_rate": rate, "points": _chips(parts[0])}]
        groups.append({"label": name, "usage_rate": rate, "spreads": spreads})
    return groups


def parse_page(page):
    basis = xdata(page, "pokemonShowBasis")
    trend = xdata(page, "pokemonShowTrend")
    return {
        "forms": basis["forms"],
        "moves": [json.loads(html.unescape(x)) for x in re.findall(r'data-move-detail="(\{.*?\})"', page)],
        "items": parse_items(page),
        "item_keys": {d["name"]: str(k) for k, d in trend["itemDetails"].items()},
        "abilities": parse_abilities(page),
        "natures": parse_natures(page),
        "spread_groups": parse_spread_groups(page),
    }


# ---------------------------------------------------------------- マスタ

def move_record(d):
    tags = d.get("tags") or []
    prio = next((int(t[3:]) for t in tags if t.startswith("優先度")), 0)
    desc = d.get("description") or None
    boosts = None
    m = re.search(r"自分の(攻撃|防御|特攻|特防|素早さ)を(\d+)段階上げる", desc or "")
    if d["category_label"] == "変化" and m:
        boosts = [{"stat": STAT_JP[m.group(1)], "stages": int(m.group(2))}]
    num = lambda v: None if v in (None, "", "−", "-") else int(v)
    return {"id": f"move_{d['move_key']}", "name": d["name"], "type": d["type"]["name"],
            "category": d["category_label"], "power": num(d.get("power")), "accuracy": num(d.get("accuracy")),
            "pp": num(d.get("pp")), "additional_effect": desc, "effect_chance": None, "priority": prio,
            "makes_contact": "接触" in tags, "boosts_own_stat": boosts}


def stats_of(form):
    return {k: form["stats"][k]["base"] for k in ("hp", "attack", "defense", "sp_attack", "sp_defense", "speed")}


# ---------------------------------------------------------------- 組み立て

def build_species(rank, key, p, masters, added):
    moves_m, abil_m, items_m = masters
    base = p["forms"][key]
    name = base["display_name"]
    pid = f"pokemon_{key}"
    abil_by_name = {a["name"]: a for f in p["forms"].values() for a in f["abilities"]}

    def ability_id(n):
        a = abil_by_name[n]
        aid = f"ability_{a['ability_key']}"
        if aid not in abil_m:
            abil_m[aid] = {"id": aid, "name": n, "description": a["description"], "category": "その他",
                           "caution_flag": False, "effect_modifiers": []}
            added["abilities"].append(n)
        return aid

    # 技：採用率上位の攻撃技5つ＋上位5位以内の積み技
    ranked = sorted(p["moves"], key=lambda d: d["rank"])
    for d in ranked:
        mid = f"move_{d['move_key']}"
        if mid not in moves_m:
            moves_m[mid] = move_record(d)
            added["moves"].append(d["name"])
    attack = [d for d in ranked if d["category_label"] != "変化"][:ATTACK_MOVES]
    boost = [d for d in ranked[:5] if d["name"] in BOOST_MOVES]
    chosen = sorted({d["move_key"]: d for d in attack + boost}.values(), key=lambda d: d["rank"])
    move_ids = [f"move_{d['move_key']}" for d in chosen]
    boost_flag = bool(boost)

    stones = [(n, r) for n, r in p["items"] if "ナイト" in n]
    stone_rate = round(sum(r for _, r in stones), 1) if stones else None
    items = [{"item_id": f"item_{p['item_keys'][n]}", "usage_rate": r} for n, r in p["items"]
             if r >= USAGE_THRESHOLD and n in p["item_keys"] and f"item_{p['item_keys'][n]}" in items_m][:5]
    natures = [n for n in p["natures"] if n["usage_rate"] >= USAGE_THRESHOLD]
    spreads = [g for g in p["spread_groups"] if g["usage_rate"] >= USAGE_THRESHOLD]
    normal_spreads = spreads
    if name in NORMAL_FORM_EXCLUDE:
        excluded_stat = NORMAL_FORM_EXCLUDE[name]
        normal_spreads = [g for g in spreads
                          if not any(x["points"][excluded_stat] >= INVESTED_POINTS for x in g["spreads"])]

    def mega_spreads(form):
        """メガ形態はメガ後の戦い方に合う振り方だけにする：メガ後の種族値でこうげき・とくこうの高い方に
        16ポイント以上振っている振り方を残す（データは通常形態と共通の集計のため）。守備専用のポケモンは絞らない"""
        if form["display_name"] in DEFENSIVE_ONLY:
            return spreads
        st = stats_of(form)
        key = "attack" if st["attack"] >= st["sp_attack"] else "sp_attack"
        out = []
        for g in spreads:
            kept = [x for x in g["spreads"] if x["points"][key] >= INVESTED_POINTS]
            if kept:
                out.append(dict(g, spreads=kept))
        return out or spreads

    def row(form_key, form, is_mega):
        fname = form["display_name"]
        abil = ([(n, r) for n, r in p["abilities"]] if not is_mega
                else [(form["abilities"][0]["name"], 100.0)])
        return {
            "id": f"pokemon_{form_key}", "name": fname, "types": [t["name"] for t in form["types"]],
            "abilities": [ability_id(n) for n, _ in abil], "base_stats": stats_of(form), "moves": move_ids,
            "snapshot_id": None, "usage_rank": rank, "usage_rate": None,
            "item_candidates": [] if is_mega else items, "mega_stone_usage_rate": stone_rate,
            "is_defensive_only": fname in DEFENSIVE_ONLY, "boost_move_used_flag_eligible": boost_flag,
            "is_mega": is_mega, "mega_of": pid if is_mega else None, "fixed_mega_only": False,
            "mega_fixed_note": None, "form_selection": "fixed",
            "ability_usage": [{"ability_id": ability_id(n), "usage_rate": r} for n, r in abil],
            "nature_usage": natures, "stat_point_usage": mega_spreads(form) if is_mega else normal_spreads,
        }

    normal = row(key, base, False)
    rate = stone_rate or 0
    if name in FORCE_NORMAL or rate <= MEGA_RANDOM_RATE or not stones:
        if name in FORCE_NORMAL and rate > MEGA_RANDOM_RATE:
            normal["fixed_mega_only"] = True
            normal["mega_fixed_note"] = (f"メガ化率{rate}%だが、通常/メガで技カテゴリ（物理・特殊）が大きく異なり"
                                         f"計算の前提が崩れるため、通常{name}に固定して出題する")
        return [normal]

    # メガ／メガZ／メガX・Yは通常からの分岐：所持率が最も高いメガストーンの形態を採用
    top_stone = max(stones, key=lambda s: s[1])[0]
    suffix = top_stone[-1] if top_stone[-1] in "ＸＹＺ" else None
    mega_key, mega_form = next((k, f) for k, f in p["forms"].items()
                               if f["display_name"].startswith("メガ")
                               and (f["display_name"][-1] == suffix if suffix else f["display_name"][-1] not in "ＸＹＺ"))
    mega = row(mega_key, mega_form, True)
    for r in (normal, mega):
        r["fixed_mega_only"] = True
    stone_note = f"（内 {top_stone} {dict(stones)[top_stone]}%）"
    if name in FORCE_MEGA:
        normal["form_selection"], mega["form_selection"] = "excluded", "fixed"
        mega["mega_fixed_note"] = f"メガストーン所持率{rate}%だが、指示により{mega['name']}に固定して出題する"
        normal["mega_fixed_note"] = f"{mega['name']}に固定するため通常形態は出題しない"
    elif rate > MEGA_FIXED_RATE:
        normal["form_selection"], mega["form_selection"] = "excluded", "fixed"
        mega["mega_fixed_note"] = f"メガストーン所持率が{rate}%{stone_note}と高いため、{mega['name']}に固定して出題する"
        normal["fixed_mega_only"] = False
    else:
        normal["form_selection"] = mega["form_selection"] = "random"
        note = f"メガストーン所持率が{rate}%（30~60%帯）のため、通常／メガをランダムに出題する"
        normal["mega_fixed_note"] = mega["mega_fixed_note"] = note
    return [normal, mega]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--rule", type=int, default=0, help="0=シングル")
    ap.add_argument("--refetch", action="store_true")
    args = ap.parse_args()
    cache = CACHE / f"s{args.season}_r{args.rule}"
    query = f"season={args.season}&rule={args.rule}"

    list_url = f"{BASE_URL}/pokemon/list?{query}"
    ranking, title = parse_list(fetch(list_url, cache / "list.html", args.refetch))
    season_label = re.search(r"シーズン(\S+?)（", title).group(1)
    assert len(ranking) == TOP_N, f"上位{TOP_N}位を取得できませんでした: {len(ranking)}"

    load = lambda n: json.loads((DATA / f"{n}.json").read_text(encoding="utf-8"))
    moves_m = {m["id"]: m for m in load("moves")}
    abil_m = {a["id"]: a for a in load("abilities")}
    items_m = {i["id"]: i for i in load("items")}
    added = {"moves": [], "abilities": []}

    snapshot_id = f"{season_label}_single" if args.rule == 0 else f"{season_label}_double"
    rows = []
    for rank, key in ranking:
        page = fetch(f"{BASE_URL}/pokemon/show/{key}?{query}", cache / f"{key}.html", args.refetch)
        for r in build_species(rank, key, parse_page(page), (moves_m, abil_m, items_m), added):
            r["snapshot_id"] = snapshot_id
            rows.append(r)

    fetched = datetime.date.fromtimestamp((cache / "list.html").stat().st_mtime).isoformat()
    opt = re.search(r'<option value="%d"[^>]*>\s*(\S+)\s*\(([^)]*)\)\s*(\d{4}/\d{1,2}/\d{1,2})\s*-\s*(\d{4}/\d{1,2}/\d{1,2})'
                    % args.season, (cache / "list.html").read_text(encoding="utf-8"))
    period = ""
    if opt:
        end = datetime.datetime.strptime(opt.group(4), "%Y/%m/%d").date()
        state = "シーズン終了後の確定データ" if datetime.date.fromisoformat(fetched) >= end else "シーズン進行中のデータ"
        period = f"レギュレーション{opt.group(2)}、期間 {opt.group(3)}-{opt.group(4)}、{state}。"
    snapshot = [{
        "snapshot_id": snapshot_id, "date": fetched, "source_url": list_url,
        "description": f"シーズン{season_label}（{'シングル' if args.rule == 0 else 'ダブル'}バトル）使用率上位{TOP_N}位。"
                       f"{period}{fetched}取得。ランキング・採用技・特性・持ち物・性格・能力ポイントの採用率データ。",
    }]

    def dump(name, obj):
        (DATA / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    dump("pokemon", rows)
    dump("usage_snapshot", snapshot)
    dump("moves", sorted(moves_m.values(), key=lambda m: int(m["id"].split("_")[1])))
    dump("abilities", sorted(abil_m.values(), key=lambda a: int(a["id"].split("_")[1])))
    print(f"{title}: {len(rows)}行（{TOP_N}種）を書き出しました")
    for kind, names in added.items():
        if names:
            print(f"マスタに追加した{kind}: {', '.join(names)}  ← 特性は category を手で確認すること")


if __name__ == "__main__":
    main()
