// damage_sense 計算エンジン（main.py のJavaScript移植版）
// 計算結果は main.py と一致させること（test_web.py で照合している）。
// ブラウザでも jsc でも動くよう、グローバル変数 DamageEngine として公開する。
var DamageEngine = (function () {
  "use strict";

  var LEVEL = 50;
  var MAX_MIN_PERCENT = 110;
  var ANSWER_CAP = 100;
  var P_BOOST_USED = 0.5;
  // 最終補正として掛かる持ち物（実機の4096分率）。それ以外の持ち物は威力補正として items.json の倍率で掛ける
  var FINAL_MOD_ITEMS = { "たつじんのおび": 4915, "いのちのたま": 5324 };
  var USAGE_THRESHOLD = 10;         // 採用率がこれ未満の性格・振り方・持ち物は選ばない
  var INVESTED_POINTS = 16;  // これ以上振ったステータスを「特化側」とみなす（性格の選択に使う）

  var TYPE_CHART = {
    "ノーマル": { "いわ": 0.5, "ゴースト": 0, "はがね": 0.5 },
    "ほのお": { "ほのお": 0.5, "みず": 0.5, "くさ": 2, "こおり": 2, "むし": 2, "いわ": 0.5, "ドラゴン": 0.5, "はがね": 2 },
    "みず": { "ほのお": 2, "みず": 0.5, "くさ": 0.5, "じめん": 2, "いわ": 2, "ドラゴン": 0.5 },
    "でんき": { "みず": 2, "でんき": 0.5, "くさ": 0.5, "じめん": 0, "ひこう": 2, "ドラゴン": 0.5 },
    "くさ": { "ほのお": 0.5, "みず": 2, "くさ": 0.5, "どく": 0.5, "じめん": 2, "ひこう": 0.5, "むし": 0.5, "いわ": 2, "ドラゴン": 0.5, "はがね": 0.5 },
    "こおり": { "ほのお": 0.5, "みず": 0.5, "くさ": 2, "こおり": 0.5, "じめん": 2, "ひこう": 2, "ドラゴン": 2, "はがね": 0.5 },
    "かくとう": { "ノーマル": 2, "こおり": 2, "どく": 0.5, "ひこう": 0.5, "エスパー": 0.5, "むし": 0.5, "いわ": 2, "ゴースト": 0, "あく": 2, "はがね": 2, "フェアリー": 0.5 },
    "どく": { "くさ": 2, "どく": 0.5, "じめん": 0.5, "いわ": 0.5, "ゴースト": 0.5, "はがね": 0, "フェアリー": 2 },
    "じめん": { "ほのお": 2, "でんき": 2, "くさ": 0.5, "どく": 2, "ひこう": 0, "むし": 0.5, "いわ": 2, "はがね": 2 },
    "ひこう": { "でんき": 0.5, "くさ": 2, "かくとう": 2, "むし": 2, "いわ": 0.5, "はがね": 0.5 },
    "エスパー": { "かくとう": 2, "どく": 2, "エスパー": 0.5, "あく": 0, "はがね": 0.5 },
    "むし": { "ほのお": 0.5, "くさ": 2, "かくとう": 0.5, "どく": 0.5, "ひこう": 0.5, "エスパー": 2, "ゴースト": 0.5, "あく": 2, "はがね": 0.5, "フェアリー": 0.5 },
    "いわ": { "ほのお": 2, "こおり": 2, "かくとう": 0.5, "じめん": 0.5, "ひこう": 2, "むし": 2, "はがね": 0.5 },
    "ゴースト": { "ノーマル": 0, "エスパー": 2, "ゴースト": 2, "あく": 0.5 },
    "ドラゴン": { "ドラゴン": 2, "はがね": 0.5, "フェアリー": 0 },
    "あく": { "かくとう": 0.5, "エスパー": 2, "ゴースト": 2, "あく": 0.5, "フェアリー": 0.5 },
    "はがね": { "ほのお": 0.5, "みず": 0.5, "でんき": 0.5, "こおり": 2, "いわ": 2, "はがね": 0.5, "フェアリー": 2 },
    "フェアリー": { "ほのお": 0.5, "かくとう": 2, "どく": 0.5, "ドラゴン": 2, "あく": 2, "はがね": 0.5 }
  };

  function set(arr) { var o = {}; arr.forEach(function (x) { o[x] = true; }); return o; }
  var UNSUPPORTED_MOVES = set(["ミラーコート", "メタルバースト", "くさむすび", "つららばり", "みずしゅりけん",
    "トリプルアクセル", "ダブルウイング", "スケイルショット", "ボディプレス", "イカサマ"]);
  var PUNCH_MOVES = set(["れいとうパンチ", "かみなりパンチ", "ほのおのパンチ", "マッハパンチ", "バレットパンチ", "コメットパンチ", "ドレインパンチ", "でんこうそうげき"]);
  var PULSE_MOVES = set(["みずのはどう", "あくのはどう", "りゅうのはどう", "はどうだん", "だいちのはどう"]);
  var SOUND_MOVES = set(["ハイパーボイス", "うたかたのアリア", "むしのさざめき", "フレアソング", "みわくのボイス", "バークアウト"]);
  var TARGET_DEFENSE_SPECIAL_MOVES = set(["サイコショック"]);  // 特殊技だが相手のぼうぎょで計算
  var RECOIL_MOVES = set(["すてみタックル", "フレアドライブ", "ブレイブバード", "ウッドハンマー", "ウェーブタックル", "とびひざげり"]);
  var ALWAYS_CRIT_MOVES = set(["トリックフラワー"]);
  // 場に出たターンにしか使えない技。積み技を使った後（＝出たターンではない）には使えない
  var FIRST_TURN_MOVES = set(["であいがしら", "ねこだまし"]);
  var BOOST_MOVES = set(["りゅうのまい", "つるぎのまい", "わるだくみ", "ちょうのまい"]);
  var WEATHER_SETTERS = { "ひでり": "sunny", "あめふらし": "rain", "すなおこし": "sandstorm", "ゆきふらし": "snow" };
  var FIELD_SETTERS = { "エレキメイカー": "electric_terrain", "グラスメイカー": "grassy_terrain",
    "サイコメイカー": "psychic_terrain", "ミストメイカー": "misty_terrain" };
  var WEATHER_BALL_TYPE = { sunny: "ほのお", rain: "みず", sandstorm: "いわ", snow: "こおり" };
  var TERRAIN_PULSE_TYPE = { electric_terrain: "でんき", grassy_terrain: "くさ",
    psychic_terrain: "エスパー", misty_terrain: "フェアリー" };
  var IMMUNITY_ABILITIES = { "ふゆう": "じめん", "ちくでん": "でんき", "ひらいしん": "でんき" };

  // ---------------------------------------------------------------- 基本部品

  function pokeRound(x) {
    var f = Math.floor(x);
    return x - f > 0.5 ? f + 1 : f;
  }
  function chainMods(mods) {
    var m = 4096;
    mods.forEach(function (x) { m = Math.floor((m * x + 2048) / 4096); });
    return m;
  }
  function applyMod(v, m) { return pokeRound(v * m / 4096); }
  function to4096(mult) {
    var table = { 1.1: 4505, 1.2: 4915, 1.3: 5325, 1.5: 6144, 2: 8192, 0.5: 2048 };
    return table[mult] !== undefined ? table[mult] : Math.round(mult * 4096);
  }
  function calcStat(base, points, nature, isHp) {
    if (isHp) return base + 75 + points;
    // 浮動小数の誤差を避けるため整数で計算（1.1倍→×11÷10、0.9倍→×9÷10）
    return Math.floor((base + 20 + points) * Math.round((nature || 1) * 10) / 10);
  }
  function applyRank(stat, stages) {
    if (stages >= 0) return Math.floor(stat * (2 + stages) / 2);
    return Math.floor(stat * 2 / (2 - stages));
  }
  function typeEffectiveness(moveType, defTypes, moveName) {
    var eff = 1;
    defTypes.forEach(function (t) {
      var m = TYPE_CHART[moveType][t];
      if (m === undefined) m = 1;
      if (moveName === "フリーズドライ" && t === "みず") m = 2;
      eff *= m;
    });
    return eff;
  }

  // ---------------------------------------------------------------- 対戦者

  function Combatant(row, ability) {
    this.row = row;
    this.ability = ability;
    this.item = null;
    this.points = {};
    this.nature = {};
    this.natureName = null;
    this.spreadLabel = null;
    this.boosts = {};
    this.boostMove = null;
  }
  Combatant.prototype.stat = function (key) {
    return calcStat(this.row.base_stats[key], this.points[key] || 0, this.nature[key] || 1, key === "hp");
  };
  Combatant.prototype.isGrounded = function () {
    return this.row.types.indexOf("ひこう") < 0 && this.ability !== "ふゆう";
  };

  // ---------------------------------------------------------------- ダメージ計算

  function itemApplies(item, move, moveType, physical, eff) {
    var rule = item.applies_to;
    if (item.name === "たつじんのおび" && eff <= 1) return false;
    if (rule.move_type && rule.move_type !== moveType) return false;
    if (rule.move_category && rule.move_category !== (physical ? "物理" : "特殊")) return false;
    if (rule.move_id && rule.move_id !== move.id) return false;
    return true;
  }

  // 戻り値: 16通りのダメージと計算の内訳（trace）。技が出せない/無効なら null
  function calcDamage(data, atk, dfn, move, battle) {
    var name = move.name;
    if (move.category === "変化" || move.power === null || UNSUPPORTED_MOVES[name]) return null;
    if (name === "ソーラービーム" && battle.weather !== "sunny") return null;
    if (name === "エレクトロビーム" && battle.weather !== "rain") return null;  // あめ以外は溜めが必要
    if (name === "でんこうそうげき" && atk.row.types.indexOf("でんき") < 0) return null;

    var notes = [];
    var trace = { power: [], attack: [], defense: [], middle: [], final: [] };
    var moldBreaker = atk.ability === "かたやぶり";
    var dfnAbility = moldBreaker ? null : dfn.ability;
    var physical = move.category === "物理";
    var moveType = move.type;
    var basePower = move.power;

    if (name === "ウェザーボール" && battle.weather) {
      moveType = WEATHER_BALL_TYPE[battle.weather]; basePower = 100;
    }
    if (name === "だいちのはどう" && battle.field && atk.isGrounded()) {
      moveType = TERRAIN_PULSE_TYPE[battle.field]; basePower = 100;
    }
    if (name === "ワイドフォース" && battle.field === "psychic_terrain" && atk.isGrounded()) basePower = 120;
    if (name === "アシストパワー") {
      var up = 0;
      Object.keys(atk.boosts).forEach(function (k) { if (atk.boosts[k] > 0) up += atk.boosts[k]; });
      basePower = 20 + 20 * up;
    }
    var skinBoost = false;
    if (moveType === "ノーマル" && (atk.ability === "スカイスキン" || atk.ability === "フェアリースキン")) {
      moveType = atk.ability === "スカイスキン" ? "ひこう" : "フェアリー";
      skinBoost = true;
    }
    if (atk.ability === "うるおいボイス" && SOUND_MOVES[name]) moveType = "みず";

    var eff = typeEffectiveness(moveType, dfn.row.types, name);
    if (dfnAbility && IMMUNITY_ABILITIES[dfnAbility] === moveType) eff = 0;
    if (eff === 0) return null;

    // 威力補正
    var pm = [];
    function addP(mod, label) { pm.push(mod); trace.power.push({ label: label, mod: mod }); }
    if (skinBoost) addP(4915, atk.ability);
    if (atk.ability === "テクニシャン" && basePower <= 60) addP(6144, "テクニシャン");
    if (atk.ability === "てつのこぶし" && PUNCH_MOVES[name]) addP(4915, "てつのこぶし");
    if (atk.ability === "メガランチャー" && PULSE_MOVES[name]) addP(6144, "メガランチャー");
    if (atk.ability === "かたいツメ" && move.makes_contact) addP(5325, "かたいツメ");
    if (atk.ability === "すてみ" && RECOIL_MOVES[name]) addP(4915, "すてみ");
    if (atk.ability === "すなのちから" && battle.weather === "sandstorm" &&
        (moveType === "いわ" || moveType === "じめん" || moveType === "はがね")) addP(5325, "すなのちから");
    if (name === "はたきおとす" && !dfn.row.is_mega) {
      addP(6144, "はたきおとす（道具あり）");
      notes.push("はたきおとす：防御側が道具を持っている前提で威力1.5倍");
    }
    if (name === "アクロバット") notes.push("アクロバット：攻撃側が道具を持っている前提で威力2倍にしない");
    if (atk.item && !FINAL_MOD_ITEMS[atk.item.name] && itemApplies(atk.item, move, moveType, physical, eff)) {
      addP(to4096(atk.item.multiplier), atk.item.name);
    }
    if (battle.field) {
      var fd = data.field[battle.field];
      if (atk.isGrounded() && fd.move_type_multiplier[moveType]) {
        addP(to4096(fd.move_type_multiplier[moveType]), fd.name);
      }
      if (dfn.isGrounded() && fd.defender_type_multiplier[moveType] &&
          (battle.field !== "grassy_terrain" || name === "じしん")) {
        addP(to4096(fd.defender_type_multiplier[moveType]), fd.name);
      }
    }
    var power = Math.max(1, applyMod(basePower, chainMods(pm)));

    // こうげき/とくこう
    var aKey = physical ? "attack" : "sp_attack";
    var aStat = atk.stat(aKey);
    var aStage = atk.boosts[aKey] || 0;
    if (name === "エレクトロビーム") {
      aStage = Math.min(6, aStage + (atk.ability === "あまのじゃく" ? -1 : 1));
      notes.push("エレクトロビーム：攻撃前にとくこうが1段階上がる（あめのため溜めなしで攻撃）");
    }
    if (dfnAbility === "てんねん") {
      if (aStage) trace.attack.push({ label: "てんねん（ランク無視）", mod: null });
      aStage = 0;
    }
    if (aStage) trace.attack.push({ label: "ランク" + (aStage > 0 ? "+" : "") + aStage, mod: null });
    aStat = applyRank(aStat, aStage);
    var am = [];
    if (atk.ability === "サンパワー" && battle.weather === "sunny" && !physical) {
      am.push(6144); trace.attack.push({ label: "サンパワー", mod: 6144 });
    }
    if (dfnAbility === "あついしぼう" && (moveType === "ほのお" || moveType === "こおり")) {
      am.push(2048); trace.attack.push({ label: "あついしぼう", mod: 2048 });
    }
    aStat = Math.max(1, applyMod(aStat, chainMods(am)));

    // ぼうぎょ/とくぼう
    var dKey = physical || TARGET_DEFENSE_SPECIAL_MOVES[name] ? "defense" : "sp_defense";
    var dStat = dfn.stat(dKey);
    if (atk.ability !== "てんねん") dStat = applyRank(dStat, dfn.boosts[dKey] || 0);
    var dm = [];
    if (battle.weather) {
      var wd = data.weather[battle.weather];
      Object.keys(wd.defender_stat_multiplier).forEach(function (t) {
        var rule = wd.defender_stat_multiplier[t];
        if (dfn.row.types.indexOf(t) >= 0 && rule.stat === dKey) {
          dm.push(to4096(rule.multiplier));
          trace.defense.push({ label: wd.name + "（" + t + "）", mod: to4096(rule.multiplier) });
        }
      });
    }
    dStat = Math.max(1, applyMod(dStat, chainMods(dm)));

    // 基本ダメージ
    var base = Math.floor(LEVEL * 2 / 5 + 2);
    base = Math.floor(base * power * aStat / dStat);
    base = Math.floor(base / 50) + 2;
    var baseDamage = base;

    // 中略：天候・急所
    if (battle.weather) {
      var wmul = data.weather[battle.weather].move_type_multiplier[moveType];
      if (wmul) {
        base = applyMod(base, to4096(wmul));
        trace.middle.push({ label: data.weather[battle.weather].name, mod: to4096(wmul) });
      }
    }
    if (ALWAYS_CRIT_MOVES[name]) {
      base = applyMod(base, 6144);
      trace.middle.push({ label: "急所", mod: 6144 });
      notes.push(name + "：必ず急所（1.5倍）");
    }

    // 後略：タイプ一致・相性・最終補正
    var stab = 0, stabLabel = null;
    if (atk.row.types.indexOf(moveType) >= 0) {
      stab = atk.ability === "てきおうりょく" ? 8192 : 6144;
      stabLabel = stab === 8192 ? "タイプ一致（てきおうりょく）" : "タイプ一致";
    } else if (atk.ability === "へんげんじざい" || atk.ability === "リベロ") {
      stab = 6144;
      stabLabel = "タイプ一致（" + atk.ability + "：技と同じタイプに変化）";
    }
    if (stab) trace.final.push({ label: stabLabel, mod: stab });
    trace.final.push({ label: "タイプ相性", mod: null, value: eff });
    var fm = [];
    if (dfnAbility === "マルチスケイル") { fm.push(2048); trace.final.push({ label: "マルチスケイル", mod: 2048 }); }
    if (dfnAbility === "はどうのぼうご" && move.makes_contact) { fm.push(2048); trace.final.push({ label: "はどうのぼうご", mod: 2048 }); }
    if (atk.item && FINAL_MOD_ITEMS[atk.item.name] && itemApplies(atk.item, move, moveType, physical, eff)) {
      fm.push(FINAL_MOD_ITEMS[atk.item.name]);
      trace.final.push({ label: atk.item.name, mod: FINAL_MOD_ITEMS[atk.item.name] });
    }
    var finalMod = chainMods(fm);

    var damages = [];
    for (var r = 85; r <= 100; r++) {
      var d = Math.floor(base * r / 100);
      if (stab) d = applyMod(d, stab);
      d = Math.floor(d * eff);
      d = applyMod(d, finalMod);
      damages.push(Math.max(1, d));
    }
    var hp = dfn.stat("hp");
    return {
      move: move, moveType: moveType, basePower: basePower, power: power,
      attackStat: aStat, defenseStat: dStat, defenseKey: dKey, baseDamage: baseDamage, stab: stab, stabLabel: stabLabel,
      damages: damages, hp: hp, effectiveness: eff, notes: notes, trace: trace,
      minDamage: damages[0], maxDamage: damages[15],
      minPercent: damages[0] / hp * 100, maxPercent: damages[15] / hp * 100
    };
  }

  // ---------------------------------------------------------------- 出題

  function makeRng(seed) {
    if (seed === undefined || seed === null) return Math.random;
    var a = seed >>> 0;
    return function () { // mulberry32
      a = (a + 0x6D2B79F5) >>> 0;
      var t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function choice(rng, arr) { return arr[Math.floor(rng() * arr.length)]; }
  function weighted(rng, arr, weights) {
    var total = weights.reduce(function (a, b) { return a + b; }, 0);
    var x = rng() * total;
    for (var i = 0; i < arr.length; i++) { x -= weights[i]; if (x < 0) return arr[i]; }
    return arr[arr.length - 1];
  }

  function indexData(raw) {
    var byId = function (list) { var o = {}; list.forEach(function (x) { o[x.id] = x; }); return o; };
    var species = {};
    raw.pokemon.forEach(function (row) {
      var key = row.mega_of || row.id;
      (species[key] = species[key] || []).push(row);
    });
    return {
      pokemon: raw.pokemon, species: species, speciesKeys: Object.keys(species),
      moves: byId(raw.moves), abilities: byId(raw.abilities), items: byId(raw.items),
      weather: byId(raw.weather), field: byId(raw.field), evRules: raw.ev_rules,
      snapshot: raw.usage_snapshot ? raw.usage_snapshot[0] : null
    };
  }

  function pickForm(rows, rng) {
    var fixed = rows.filter(function (r) { return r.form_selection === "fixed"; });
    if (fixed.length) return fixed[0];
    return choice(rng, rows.filter(function (r) { return r.form_selection === "random"; }));
  }
  function pickAbility(data, row, rng) {
    var u = row.ability_usage;
    var chosen = weighted(rng, u, u.map(function (x) { return x.usage_rate; }));
    return data.abilities[chosen.ability_id].name;
  }
  function pickItem(data, row, rng) {
    if (row.is_mega) return null;
    var roll = rng() * 100, acc = 0;
    var cands = row.item_candidates || [];
    for (var i = 0; i < cands.length; i++) {
      var item = data.items[cands[i].item_id];
      if (item.multiplier < 1.2 || cands[i].usage_rate < USAGE_THRESHOLD) continue;
      acc += cands[i].usage_rate;
      if (roll < acc) return item;
    }
    return null;
  }
  // 攻撃時と防御時で姿が変わるポケモン（ギルガルド）は、役割に応じたフォルムの種族値と名前にする
  function battleFormRow(row, role) {
    var forms = row.battle_forms;
    if (!forms) return row;
    var f = forms[role];
    return Object.assign({}, row, { name: row.name + "（" + f.form_name + "）", base_stats: f.base_stats });
  }
  function makeCombatant(data, row, rng, role) {
    row = battleFormRow(row, role);
    var c = new Combatant(row, pickAbility(data, row, rng));
    pickSpreadAndNature(row, rng, c);
    if (role === "attacker") {
      c.item = pickItem(data, row, rng);
      // 積み技は振り方に合うもの（AS振りならこうげきが上がる技）だけを使用済みにする
      var stats = attackingStats(c);
      var boostMoves = row.moves.map(function (m) { return data.moves[m]; })
        .filter(function (m) {
          return BOOST_MOVES[m.name] && m.boosts_own_stat.some(function (b) { return stats.indexOf(b.stat) >= 0; });
        });
      if (boostMoves.length && row.boost_move_used_flag_eligible && rng() < P_BOOST_USED) {
        var bm = choice(rng, boostMoves);
        c.boostMove = bm.name;
        var sign = c.ability === "あまのじゃく" ? -1 : 1;
        bm.boosts_own_stat.forEach(function (b) {
          c.boosts[b.stat] = Math.max(-6, Math.min(6, (c.boosts[b.stat] || 0) + sign * b.stages));
        });
      }
    }
    return c;
  }
  // 採用率10%以上の振り方・性格から、採用率で重み付けして選ぶ（攻撃側・防御側共通）
  function pickSpreadAndNature(row, rng, c) {
    var groups = row.stat_point_usage;
    var group = weighted(rng, groups, groups.map(function (g) { return g.usage_rate; }));
    var spread = weighted(rng, group.spreads, group.spreads.map(function (x) { return x.usage_rate; }));
    c.points = Object.assign({}, spread.points);
    c.spreadLabel = spread.label;
    // 振り方に合う性格のみ：特化側（16ポイント以上振ったステータス）を上げ、特化側を下げない性格
    var natures = row.nature_usage.filter(function (n) {
      var inv = function (k) { return k && k !== "hp" && c.points[k] >= INVESTED_POINTS; };
      return inv(n.up) && !inv(n.down);
    });
    if (!natures.length) natures = row.nature_usage;
    var nature = weighted(rng, natures, natures.map(function (n) { return n.usage_rate; }));
    c.natureName = nature.name;
    c.nature = {};
    if (nature.up) c.nature[nature.up] = 1.1;
    if (nature.down) c.nature[nature.down] = 0.9;
  }
  // 天候/フィールドを発生させる特性の持ち主を決める（main.py の resolve_setter と同じ規則）。
  // 特性を持つポケモンがいなければ発生しない。両方が持つ場合は後から発動した方で上書き：
  //   1. メガシンカしたポケモン  2. すばやさが遅いポケモン  3. 同速ならランダム
  function resolveSetter(atk, dfn, setters, rng) {
    var cands = [atk, dfn].filter(function (c) { return setters[c.ability]; });
    if (!cands.length) return { id: null, note: null };
    if (cands.length === 1) return { id: setters[cands[0].ability], note: cands[0].row.name + "の" + cands[0].ability };
    var a = cands[0], d = cands[1], win, lose, why;
    if (a.row.is_mega !== d.row.is_mega) {
      win = a.row.is_mega ? a : d; lose = win === a ? d : a;
      why = "メガシンカした" + win.row.name + "が後から発動して" + lose.row.name + "の" + lose.ability + "を上書き";
    } else if (a.stat("speed") !== d.stat("speed")) {
      win = a.stat("speed") < d.stat("speed") ? a : d; lose = win === a ? d : a;
      why = "すばやさが遅い" + win.row.name + "（" + win.stat("speed") + "）が後から発動して" +
        lose.row.name + "（" + lose.stat("speed") + "）の" + lose.ability + "を上書き";
    } else {
      win = choice(rng, cands); lose = win === a ? d : a;
      why = "同速（" + win.stat("speed") + "）のためランダムで" + win.row.name + "が後から発動";
    }
    return { id: setters[win.ability], note: win.row.name + "の" + win.ability + "（" + why + "）" };
  }
  function decideBattle(atk, dfn, rng) {
    var w = resolveSetter(atk, dfn, WEATHER_SETTERS, rng);
    var f = resolveSetter(atk, dfn, FIELD_SETTERS, rng);
    return { weather: w.id, field: f.id, weatherNote: w.note, fieldNote: f.note };
  }
  // 振り方から攻撃側の戦い方を決める：こうげき/とくこうのうち16ポイント以上振った方（両方・どちらも無しなら両方）
  function attackingStats(c) {
    var inv = ["attack", "sp_attack"].filter(function (k) { return (c.points[k] || 0) >= INVESTED_POINTS; });
    return inv.length === 1 ? inv : ["attack", "sp_attack"];
  }
  // 振り方に合う分類の技だけを使う（AS振りなら物理技、CS振りなら特殊技）
  function bestMove(data, atk, dfn, battle) {
    var best = null;
    var cats = attackingStats(atk).map(function (k) { return k === "attack" ? "物理" : "特殊"; });
    atk.row.moves.forEach(function (m) {
      if (cats.indexOf(data.moves[m].category) < 0) return;
      if (atk.boostMove && FIRST_TURN_MOVES[data.moves[m].name]) return;  // 積み技の後は出たターンではない
      var r = calcDamage(data, atk, dfn, data.moves[m], battle);
      if (!r) return;
      if (!best || r.maxDamage > best.maxDamage ||
          (r.maxDamage === best.maxDamage && r.minDamage > best.minDamage)) best = r;
    });
    return best;
  }
  function generateQuestion(data, rng) {
    for (var i = 0; i < 1000; i++) {
      var keys = data.speciesKeys;
      var ai = Math.floor(rng() * keys.length);
      var di = Math.floor(rng() * (keys.length - 1));
      if (di >= ai) di++;
      var aRow = pickForm(data.species[keys[ai]], rng);
      if (aRow.is_defensive_only) continue;
      var dRow = pickForm(data.species[keys[di]], rng);
      var atk = makeCombatant(data, aRow, rng, "attacker");
      var dfn = makeCombatant(data, dRow, rng, "defender");
      var battle = decideBattle(atk, dfn, rng);
      var result = bestMove(data, atk, dfn, battle);
      if (!result || result.minPercent > MAX_MIN_PERCENT) continue;
      return {
        attacker: atk, defender: dfn, battle: battle, result: result,
        answer: Math.min(ANSWER_CAP, result.minPercent)
      };
    }
    throw new Error("条件を満たす問題を生成できませんでした");
  }

  return {
    indexData: indexData, generateQuestion: generateQuestion, calcDamage: calcDamage,
    Combatant: Combatant, makeRng: makeRng, calcStat: calcStat, typeEffectiveness: typeEffectiveness,
    decideBattle: decideBattle, MAX_MIN_PERCENT: MAX_MIN_PERCENT, ANSWER_CAP: ANSWER_CAP
  };
})();
