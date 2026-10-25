// damage_sense 画面ロジック。計算は engine.js（DamageEngine）に任せる
(function () {
  "use strict";

  var E = DamageEngine;
  var data = E.indexData(GAME_DATA);
  var rng = E.makeRng();
  var NORMAL_TOLERANCE = 5;
  var CHALLENGE_QUESTIONS = 10;
  var BEST_KEY = "damage_sense.challengeBest";
  var SITE_URL = "https://wataame25.github.io/damage_sense/";  // 共有時に付けるリンク（GitHub Pages）
  var SHARE_TAG = "#ダメージ感覚";

  var TYPE_COLOR = {
    "ノーマル": "#9a9a7a", "ほのお": "#e8742f", "みず": "#4a86e8", "でんき": "#d9ad1c", "くさ": "#5aa83e",
    "こおり": "#4fb7b3", "かくとう": "#b8322b", "どく": "#9a43a0", "じめん": "#c69a45", "ひこう": "#8c7fd9",
    "エスパー": "#e8507c", "むし": "#93a51f", "いわ": "#a99037", "ゴースト": "#6a5394", "ドラゴン": "#6236e0",
    "あく": "#6b5546", "はがね": "#8f8fac", "フェアリー": "#d97ba6"
  };
  var STAT_LABEL = { hp: "HP", attack: "こうげき", defense: "ぼうぎょ", sp_attack: "とくこう", sp_defense: "とくぼう" };

  var state = { title: true, mode: "easy", q: null, answered: false, history: [], options: null, guess: null, finished: false };

  var $main = document.getElementById("main");
  var $status = document.getElementById("status");

  // ------------------------------------------------------------ 小物

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function pct(x) { return x.toFixed(1) + "%"; }
  function typeChip(t) { return '<span class="type" style="background:' + (TYPE_COLOR[t] || "#888") + '">' + esc(t) + "</span>"; }
  function storageGet(k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } }
  function storageSet(k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* 保存できなくても続行 */ } }
  function sampleN(arr, n) {
    var a = arr.slice();
    for (var i = a.length - 1; i > 0; i--) { var j = Math.floor(rng() * (i + 1)); var t = a[i]; a[i] = a[j]; a[j] = t; }
    return a.slice(0, n);
  }

  function itemLabel(c) {
    if (!c.item) return "なし（火力アップ系以外）";
    var rule = c.item.applies_to, target;
    if (c.item.name === "たつじんのおび") target = "効果バツグンの技";
    else if (rule.move_type) target = rule.move_type + "技";
    else if (rule.move_category) target = rule.move_category + "技";
    else target = "全ての攻撃技";
    return esc(c.item.name) + ' <span class="flag up">' + esc(target) + " ×" + c.item.multiplier + "</span>";
  }
  function statBlock(c, key) {
    var n = c.nature[key] || 1;
    var nat = n > 1 ? ' ・ <span class="flag up">性格↑</span>' : n < 1 ? ' ・ <span class="flag down">性格↓</span>' : "";
    return '<div class="stat"><span class="stat-note">' + STAT_LABEL[key] + '</span><span class="stat-val">' + c.stat(key) +
      '</span><span class="stat-note">種族値' + c.row.base_stats[key] + " ・ " + (c.points[key] || 0) + "振り" + nat + "</span></div>";
  }
  function rankLabel(c, key) {
    var st = c.boosts[key] || 0;
    var cls = st > 0 ? "up" : st < 0 ? "down" : "";
    return STAT_LABEL[key] + ' <span class="flag rank ' + cls + '">' + (st > 0 ? "+" + st : st < 0 ? String(st) : "±0") + "</span>";
  }
  var STAT_SHORT = { hp: "H", attack: "A", defense: "B", sp_attack: "C", sp_defense: "D", speed: "S" };
  function natureLabel(c) {
    var up = Object.keys(c.nature).filter(function (k) { return c.nature[k] > 1; })[0];
    var down = Object.keys(c.nature).filter(function (k) { return c.nature[k] < 1; })[0];
    return esc(c.natureName) + (up ? '<span class="stat-note">（' + STAT_SHORT[up] + "↑" + STAT_SHORT[down] + "↓）</span>" : "");
  }
  function spreadLabel(c) {
    var parts = ["hp", "attack", "defense", "sp_attack", "sp_defense", "speed"].filter(function (k) { return c.points[k]; })
      .map(function (k) { return STAT_SHORT[k] + c.points[k]; });
    return '<span class="spread">' + (parts.join(" ") || "無振り") + "</span>";
  }
  // 確定数（防御側はHP満タン、乱数は16通り）
  function koLabel(r) {
    if (r.minDamage >= r.hp) return "確定1発";
    if (r.maxDamage >= r.hp) return "乱数1発";
    for (var n = 2; n <= 6; n++) {
      if (r.minDamage * n >= r.hp) return "確定" + n + "発";
      if (r.maxDamage * n >= r.hp) return "乱数" + n + "発";
    }
    return "7発以上";
  }

  // ------------------------------------------------------------ 出題

  function newQuestion() {
    state.q = E.generateQuestion(data, rng);
    state.answered = false;
    state.guess = null;
    state.options = state.mode === "easy" ? makeChoices(state.q) : null;
    render();
    window.scrollTo(0, 0);
    var input = document.getElementById("guess");
    if (input) input.focus({ preventScroll: true });
  }

  // 4択：正解レンジ＋倍率をずらしたダミー3つ（main.py の easy_choices と同じ考え方）
  function makeChoices(q) {
    var lo = q.result.minPercent, hi = q.result.maxPercent;
    var opts = [{ lo: lo, hi: hi, correct: true }].concat(
      sampleN([0.5, 0.67, 0.8, 1.25, 1.5, 2.0], 3).map(function (f) { return { lo: lo * f, hi: hi * f, correct: false }; }));
    return sampleN(opts, 4);
  }

  function submitChoice(i) {
    if (state.answered) return;
    var opt = state.options[i];
    state.answered = true;
    state.guess = { choice: i, correct: opt.correct };
    record(opt.correct, null);
    render();
  }

  function submitNumber() {
    if (state.answered) return;
    var input = document.getElementById("guess");
    var v = parseFloat(input.value);
    var err = document.getElementById("guess-error");
    if (isNaN(v) || v < 0) { err.textContent = "0以上の数値を入力してください（例: 42.5）"; input.focus(); return; }
    var diff = Math.abs(v - state.q.answer);
    state.answered = true;
    state.guess = { value: v, diff: diff, correct: diff <= NORMAL_TOLERANCE };
    record(state.guess.correct, diff);
    render();
  }

  function record(correct, diff) {
    var q = state.q;
    state.history.push({
      attacker: q.attacker.row.name, defender: q.defender.row.name, move: q.result.move.name,
      answer: q.answer, guess: state.guess.value, diff: diff, correct: correct
    });
  }

  function next() {
    if (state.mode === "challenge" && state.history.length >= CHALLENGE_QUESTIONS) { finish(); return; }
    newQuestion();
  }

  function finish() {
    state.finished = true;
    if (state.mode === "challenge") {
      var total = state.history.reduce(function (a, h) { return a + h.diff; }, 0);
      var best = parseFloat(storageGet(BEST_KEY));
      state.prevBest = isNaN(best) ? null : best;
      if (isNaN(best) || total < best) storageSet(BEST_KEY, String(total));
    }
    render();
    window.scrollTo(0, 0);
  }

  function setMode(mode) {
    state.title = false;
    state.mode = mode;
    state.history = [];
    state.finished = false;
    newQuestion();
  }

  function goTitle() {
    state.title = true;
    state.finished = false;
    render();
    window.scrollTo(0, 0);
  }

  // ------------------------------------------------------------ 描画

  var MODES = [
    { key: "easy", name: "簡単", how: "4つの「最低〜最高ダメージ％」から選ぶ", goal: "正しい範囲を選べば正解" },
    { key: "normal", name: "普通", how: "最低乱数のダメージ％を数字で入力", goal: "誤差±" + NORMAL_TOLERANCE + "%以内で正解" },
    { key: "challenge", name: "チャレンジ", how: "最低乱数のダメージ％を入力（全" + CHALLENGE_QUESTIONS + "問）", goal: "誤差の合計が小さいほど高成績" }
  ];

  function renderTitle() {
    var best = parseFloat(storageGet(BEST_KEY));
    var html = '<section class="title reveal">' +
      '<div class="hero"><p class="hero-kicker">ポケモンチャンピオンズ ダメージ計算トレーニング</p>' +
      '<p class="hero-logo">ダメージ感覚</p>' +
      '<p class="hero-lead">この技で、相手のHPを何％削れる？<br>実戦でよく使われている型どうしの対面で、ダメージの感覚を鍛えよう。</p></div>' +
      '<div class="mode-cards">';
    MODES.forEach(function (m) {
      html += '<button type="button" class="mode-card" data-start="' + m.key + '"><span class="mc-name">' + m.name + "</span>" +
        '<span class="mc-how">' + esc(m.how) + '</span><span class="mc-goal">' + esc(m.goal) + "</span>" +
        (m.key === "challenge" && !isNaN(best) ? '<span class="mc-best">自己ベスト ' + best.toFixed(1) + "%</span>" : "") +
        '<span class="mc-go">はじめる →</span></button>';
    });
    html += "</div>" +
      '<div class="guide"><h2>遊び方</h2><ol class="steps">' +
      "<li><b>対面を見る</b><span>攻撃側・使う技・防御側が表示されます。特性・持ち物・性格・能力ポイント・実数値、天候やフィールドも確認しましょう。</span></li>" +
      "<li><b>ダメージを答える</b><span>その技で防御側のHPを何％削れるかを答えます。普通・チャレンジは<em>最低乱数</em>（一番低いダメージ）の割合を入力します。</span></li>" +
      "<li><b>答え合わせ</b><span>HPバーと確定数で結果を表示。「計算の内訳」を開くと、実数値・補正・乱数16通りまで確認できます。</span></li>" +
      "</ol></div>" +
      '<div class="guide"><h2>ルールとヒント</h2><ul class="tips">' +
      "<li>最低乱数のダメージが100％を超える問題では <b>100</b> と入力してください（最低乱数が" + E.MAX_MIN_PERCENT + "％を超える問題は出ません）。</li>" +
      "<li>技は、攻撃側の技のうち相手に一番ダメージが出るものが自動で選ばれます。タイプ一致のときは表示されます。</li>" +
      "<li>Lv50・能力ポイント制（1項目最大32）で計算。防御側はHP満タン・状態異常なし、急所なし、いかくなどの能力ダウンは考えません（防御側がいかくでも、攻撃側のこうげきは下がっていない状態で計算します）。</li>" +
      "<li>簡単モードは数字キー 1〜4 で選べます。答えたあとは Enter で次の問題へ。</li>" +
      "<li>チャレンジの結果は X などで共有できます。</li>" +
      "</ul></div></section>";
    return html;
  }

  function renderStatus() {
    var h = state.history;
    var html = "";
    if (state.title) {
      $status.innerHTML = "";
      document.querySelectorAll(".modes button").forEach(function (b) { b.setAttribute("aria-pressed", "false"); });
      return;
    }
    if (state.mode === "challenge") {
      html += '<div class="pips" aria-label="進行状況">';
      for (var i = 0; i < CHALLENGE_QUESTIONS; i++) {
        var cls = i < h.length ? "done" : (i === h.length && !state.finished ? "now" : "");
        html += '<span class="pip ' + cls + '"></span>';
      }
      html += "</div>";
      var total = h.reduce(function (a, x) { return a + x.diff; }, 0);
      html += "<span>第<strong>" + Math.min(h.length + (state.answered || state.finished ? 0 : 1), CHALLENGE_QUESTIONS) +
        "</strong>問 / " + CHALLENGE_QUESTIONS + "</span><span>誤差の合計 <strong>" + total.toFixed(1) + "%</strong></span>";
      var best = parseFloat(storageGet(BEST_KEY));
      if (!isNaN(best)) html += "<span>自己ベスト <strong>" + best.toFixed(1) + "%</strong></span>";
    } else {
      var ok = h.filter(function (x) { return x.correct; }).length;
      html += "<span>回答 <strong>" + h.length + "</strong>問</span><span>正解 <strong>" + ok + "</strong>問</span>";
      html += state.mode === "easy" ? "<span>4択から最低〜最高乱数の割合を選ぶ</span>"
        : "<span>最低乱数の割合を入力、誤差±" + NORMAL_TOLERANCE + "%以内で正解</span>";
    }
    $status.innerHTML = html;
    document.querySelectorAll(".modes button").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.mode === state.mode));
    });
  }

  function renderBattle(q) {
    var a = q.attacker, d = q.defender, r = q.result;
    var physical = r.move.category === "物理";
    var aKey = physical ? "attack" : "sp_attack", dKey = r.defenseKey;
    var boost = "";
    if (a.boostMove) {
      var st = a.boosts[aKey] || 0;
      boost = "<dt>強化</dt><dd>" + esc(a.boostMove) + "を1回使用済み</dd>";
    }
    // 能力ランクは公開情報なので、変化がなくても計算に使うステータスのランクを常に表示する
    var aRank = rankLabel(a, aKey) + (r.move.name === "エレクトロビーム" ? '<span class="ability-note">技の効果で攻撃時にとくこう+1</span>' : "");
    var dRank = rankLabel(d, dKey);
    var w = q.battle.weather ? data.weather[q.battle.weather].name : "なし";
    var f = q.battle.field ? data.field[q.battle.field].name : "なし";
    var typeChanged = r.moveType !== r.move.type;
    return '<section class="battle" aria-label="出題">' +
      '<div class="side atk"><div class="role">攻撃側</div><h2 class="mon-name">' + esc(a.row.name) + "</h2>" +
      '<div class="chips">' + a.row.types.map(typeChip).join("") + "</div>" +
      '<dl class="facts"><dt>特性</dt><dd>' + esc(a.ability) + "</dd><dt>持ち物</dt><dd>" + itemLabel(a) + "</dd>" + boost + "<dt>ランク</dt><dd>" + aRank + "</dd>" +
      "<dt>性格</dt><dd>" + natureLabel(a) + "</dd><dt>振り方</dt><dd>" + spreadLabel(a) + "</dd></dl>" +
      statBlock(a, aKey) + "</div>" +
      '<div class="center"><div class="move-head"><div class="arrow">▶▶</div><h2 class="move-name">' + esc(r.move.name) + "</h2>" +
      '<div class="chips move-type">' + typeChip(r.moveType) + "</div>" +
      '<div class="move-meta"><span>' + esc(r.move.category) + "</span><span>威力 <b>" + r.basePower + "</b>" + knockOffNote(q) + "</span>" +
      (typeChanged ? "<span>（" + esc(r.move.type) + "→" + esc(r.moveType) + "）</span>" : "") + "</div>" +
      (r.stab ? '<div class="stab-row"><span class="flag stab">' + esc(r.stabLabel) + " ×" + (r.stab / 4096) + "</span></div>" : "") +
      "</div>" +
      '<div class="env"><div><span>天候</span><span>' + esc(w) + "</span></div>" +
      (q.battle.weatherNote ? '<p class="env-note">' + esc(q.battle.weatherNote) + "</p>" : "") +
      "<div><span>フィールド</span><span>" + esc(f) + "</span></div>" +
      (q.battle.fieldNote ? '<p class="env-note">' + esc(q.battle.fieldNote) + "</p>" : "") + "</div></div>" +
      '<div class="side dfn"><div class="role">防御側</div><h2 class="mon-name">' + esc(d.row.name) + "</h2>" +
      '<div class="chips">' + d.row.types.map(typeChip).join("") + "</div>" +
      '<dl class="facts"><dt>特性</dt><dd>' + esc(d.ability) + "</dd><dt>ランク</dt><dd>" + dRank + "</dd><dt>性格</dt><dd>" + natureLabel(d) +
      "</dd><dt>振り方</dt><dd>" + spreadLabel(d) + "</dd></dl>" +
      statBlock(d, "hp") + statBlock(d, dKey) + "</div>" +
      "</section>";
  }

  // はたきおとす：非メガの相手は道具を持っている前提で1.5倍、メガの相手はメガストーンを落とせないので等倍
  function knockOffNote(q) {
    if (q.result.move.name !== "はたきおとす") return "";
    return q.defender.row.is_mega ? "（メガ相手のため等倍）" : " ×1.5（相手が道具持ち）";
  }

  function renderAnswer(q) {
    if (state.mode === "easy") {
      var html = '<section class="answer"><h2>ダメージの割合（最低〜最高乱数）は？</h2><div class="choices">';
      state.options.forEach(function (o, i) {
        var cls = "";
        if (state.answered) cls = o.correct ? "correct" : (state.guess.choice === i ? "wrong" : "");
        html += '<button type="button" class="choice ' + cls + '" data-choice="' + i + '"' + (state.answered ? " disabled" : "") +
          '><span class="key">' + (i + 1) + '</span><span class="range">' + pct(o.lo) + " 〜 " + pct(o.hi) + "</span></button>";
      });
      return html + "</div></section>";
    }
    return '<section class="answer"><h2>最低乱数のダメージは防御側HPの何%？</h2>' +
      '<form class="input-row" id="guess-form" novalidate><label class="num" for="guess"><input id="guess" type="number" inputmode="decimal" step="0.1" min="0" placeholder="0.0"' +
      (state.answered ? " disabled value=\"" + state.guess.value + "\"" : "") + '><span>%</span></label>' +
      '<button class="btn" type="submit"' + (state.answered ? " disabled" : "") + ">回答する</button></form>" +
      '<p class="hint" id="guess-error" role="alert"></p>' +
      '<p class="hint">' + (state.mode === "normal" ? "誤差±" + NORMAL_TOLERANCE + "%以内で正解。" : "") +
      "最低乱数が100%を超える場合は100と入力。</p></section>";
  }

  function hpBar(r, guessPct) {
    // 0〜100% を表示。最低乱数〜最高乱数の削り幅を斜線、残りHPを色で表す
    var lo = Math.min(100, r.minPercent), hi = Math.min(100, r.maxPercent);
    var remain = 100 - lo;
    var color = remain > 50 ? "var(--hp-good)" : remain > 20 ? "var(--hp-warn)" : "var(--hp-bad)";
    // 左端から残りHPを描き、右側（削られた分）を空ける
    var html = '<div class="hpbox"><div class="hp-head"><span>' + esc(state.q.defender.row.name) + " の残りHP</span><span><b>" +
      Math.max(0, r.hp - r.maxDamage) + "〜" + Math.max(0, r.hp - r.minDamage) + "</b> / " + r.hp + "</span></div>" +
      '<div class="hpbar" role="img" aria-label="ダメージ ' + pct(r.minPercent) + "〜" + pct(r.maxPercent) + '">' +
      '<div class="hp-remain" style="width:' + (100 - hi) + "%;background:" + color + '"></div>' +
      '<div class="hp-roll" style="left:' + (100 - hi) + "%;width:" + (hi - lo) + '%"></div>';
    if (guessPct !== null && guessPct !== undefined) {
      var g = Math.max(0, Math.min(100, guessPct));
      html += '<div class="hp-guess" style="left:' + (100 - g) + '%"><span>回答 ' + pct(guessPct) + "</span></div>";
    }
    html += '</div><div class="hp-scale"><span style="left:0">HP 0%</span><span style="left:50%">50%</span><span style="left:100%">100%</span></div>' +
      '<div class="hp-legend"><span><i class="sw" style="background:' + color + '"></i>最高乱数でも残るHP</span>' +
      '<span><i class="sw" style="background:repeating-linear-gradient(135deg,var(--dmg-soft) 0 3px,transparent 3px 5px);border:1px solid var(--dmg)"></i>乱数で変わる幅</span>' +
      (guessPct !== null && guessPct !== undefined ? '<span><i class="sw" style="border-left:2px dashed var(--ink);border-radius:0;width:6px"></i>あなたの回答（右端からの削り）</span>' : "") +
      "</div></div>";
    return html;
  }

  function modLabel(m) {
    if (m.mod === null || m.mod === undefined) return esc(m.label) + (m.value !== undefined ? " ×" + m.value : "");
    return esc(m.label) + " ×" + (m.mod / 4096).toFixed(m.mod % 1024 === 0 ? 1 : 2) + "<span class=\"stat-note\">（" + m.mod + "/4096）</span>";
  }
  // 実数値の計算式（能力補正＝性格込み）
  function statFormula(c, key) {
    var b = c.row.base_stats[key], p = c.points[key] || 0, n = c.nature[key] || 1, v = c.stat(key);
    if (key === "hp") return b + " + 75 + " + p + " = " + v;
    if (n === 1) return b + " + 20 + " + p + " = " + v;
    return "floor((" + b + " + 20 + " + p + ") × " + n + ") = " + v;
  }
  function natureNote(c, key) {
    var n = c.nature[key] || 1;
    return n > 1 ? '<span class="flag up">能力補正↑ ×1.1</span>' : n < 1 ? '<span class="flag down">能力補正↓ ×0.9</span>' : "";
  }
  function statRow(label, c, key, list, used) {
    var html = "<code>" + statFormula(c, key) + "</code>" + natureNote(c, key);
    if (list && list.length) html += "　" + list.map(modLabel).join("、") + " → <code>" + used + "</code>";
    return '<div class="calc-row"><span>' + label + "</span><span>" + html + "</span></div>";
  }

  function traceRow(label, list, extra) {
    var body = list.length ? list.map(modLabel).join("、") : "なし";
    return '<div class="calc-row"><span>' + label + "</span><span>" + (extra ? extra + "　" : "") + body + "</span></div>";
  }

  function renderResult(q) {
    var r = q.result, g = state.guess, head;
    if (state.mode === "easy") {
      head = '<span class="mark ' + (g.correct ? "ok" : "ng") + '">' + (g.correct ? "正解！" : "不正解") + "</span>" +
        '<span class="sub">正解は <b>' + pct(r.minPercent) + " 〜 " + pct(r.maxPercent) + "</b></span>";
    } else {
      var label = state.mode === "challenge" ? "誤差 " + g.diff.toFixed(1) + "%" : (g.correct ? "正解！" : "不正解");
      var cls = g.correct ? "ok" : "ng";
      head = '<span class="mark ' + cls + '">' + label + "</span>" +
        '<span class="sub">正解 <b>' + pct(q.answer) + "</b>　あなたの回答 <b>" + pct(g.value) + "</b>" +
        (state.mode === "challenge" ? "" : "　誤差 <b>" + g.diff.toFixed(1) + "%</b>") + "</span>";
    }
    var last = state.mode === "challenge" && state.history.length >= CHALLENGE_QUESTIONS;
    var nextLabel = last ? "結果を見る" : "次の問題";
    var t = r.trace;
    var html = '<section class="result reveal" aria-live="polite"><div class="verdict">' + head + "</div>" +
      hpBar(r, state.mode === "easy" ? null : Math.min(100, g.value)) +
      '<div class="figures">' +
      '<div class="fig"><span>ダメージ</span><b>' + r.minDamage + "〜" + r.maxDamage + "</b></div>" +
      '<div class="fig"><span>割合</span><b>' + pct(r.minPercent) + "〜" + pct(r.maxPercent) + "</b></div>" +
      '<div class="fig"><span>タイプ相性</span><b>×' + r.effectiveness + "</b></div>" +
      '<div class="fig"><span>確定数</span><b>' + koLabel(r) + "</b></div></div>" +
      '<details class="breakdown"><summary>計算の内訳</summary><div class="calc">' +
      traceRow("威力", t.power, "<code>" + r.basePower + " → " + r.power + "</code>") +
      '<div class="calc-row"><span>実数値の式</span><span class="stat-note">(種族値 + 20 + 能力ポイント) × 能力補正 ／ HP = 種族値 + 75 + 能力ポイント</span></div>' +
      statRow(r.move.category === "物理" ? "こうげき" : "とくこう", q.attacker,
        r.move.category === "物理" ? "attack" : "sp_attack", t.attack, r.attackStat) +
      statRow(STAT_LABEL[r.defenseKey], q.defender, r.defenseKey, t.defense, r.defenseStat) +
      statRow("HP", q.defender, "hp") +
      '<div class="calc-row"><span>基本ダメージ</span><span><code>floor(floor(22 × ' + r.power + " × " + r.attackStat + " ÷ " + r.defenseStat +
      ") ÷ 50) + 2 = " + r.baseDamage + "</code></span></div>" +
      traceRow("中略（乱数前）", t.middle) +
      traceRow("後略（乱数後）", t.final) +
      '<div class="calc-row"><span>乱数16通り</span><span class="rolls">' + r.damages.join(" ") + "</span></div>" +
      '<div class="calc-row"><span>割合</span><span><code>' + r.minDamage + " ÷ " + r.hp + " = " + pct(r.minPercent) +
      "</code> 〜 <code>" + r.maxDamage + " ÷ " + r.hp + " = " + pct(r.maxPercent) + "</code></span></div>" +
      "</div>" + (r.notes.length ? '<ul class="notes">' + r.notes.map(function (n) { return "<li>" + esc(n) + "</li>"; }).join("") + "</ul>" : "") +
      "</details>" +
      '<div class="actions"><button class="btn" type="button" id="next">' + nextLabel + "</button>" +
      (state.mode !== "challenge" ? '<button class="btn ghost" type="button" id="quit">やめる</button>' : "") +
      '<span class="kbd">Enterで' + nextLabel + "</span></div></section>";
    return html;
  }

  // 1問ごとの誤差を記号に：◎2%以内 ○5%以内 △10%以内 ×それ以上
  function errorMark(diff) { return diff <= 2 ? "◎" : diff <= 5 ? "○" : diff <= 10 ? "△" : "×"; }

  function shareText() {
    var h = state.history;
    var total = h.reduce(function (a, x) { return a + x.diff; }, 0);
    var season = data.snapshot ? "（シーズン" + data.snapshot.snapshot_id.replace("_single", "") + "）" : "";
    return "ダメージ感覚 チャレンジ" + season + "\n" +
      "誤差の合計 " + total.toFixed(1) + "%（1問あたり " + (total / h.length).toFixed(1) + "%）\n" +
      h.map(function (x) { return errorMark(x.diff); }).join("") + "\n" + SHARE_TAG;
  }

  function renderShare() {
    var text = shareText();
    var xUrl = "https://twitter.com/intent/tweet?text=" + encodeURIComponent(text) + "&url=" + encodeURIComponent(SITE_URL);
    return '<div class="share"><h3>結果を共有</h3>' +
      '<pre class="share-preview" id="share-preview">' + esc(text + "\n" + SITE_URL) + "</pre>" +
      '<div class="actions">' +
      '<a class="btn" id="share-x" href="' + esc(xUrl) + '" target="_blank" rel="noopener noreferrer">Xで共有</a>' +
      '<button class="btn ghost" type="button" id="share-copy">結果をコピー</button>' +
      (navigator.share ? '<button class="btn ghost" type="button" id="share-native">その他のアプリで共有</button>' : "") +
      '<span class="kbd" id="share-status" role="status"></span></div></div>';
  }

  function copyShare() {
    var status = document.getElementById("share-status");
    var full = shareText() + "\n" + SITE_URL;
    var done = function () { status.textContent = "コピーしました"; };
    var fail = function () {
      // クリップボードが使えない環境では、プレビュー欄を選択状態にして手動コピーしてもらう
      var range = document.createRange();
      range.selectNodeContents(document.getElementById("share-preview"));
      var sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
      status.textContent = "コピーできませんでした。選択された文章をコピーしてください";
    };
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(full).then(done, fail);
      else fail();
    } catch (e) { fail(); }
  }

  function renderSummary() {
    var h = state.history;
    var html = '<section class="summary reveal"><h2>' + (state.mode === "challenge" ? "チャレンジ結果" : "おつかれさまでした") + "</h2><div class=\"big\">";
    if (state.mode === "challenge") {
      var total = h.reduce(function (a, x) { return a + x.diff; }, 0);
      html += "<div><span>誤差の合計</span><b>" + total.toFixed(1) + "%</b></div><div><span>1問あたり</span><b>" + (total / h.length).toFixed(1) + "%</b></div>";
      if (state.prevBest !== null && state.prevBest !== undefined) {
        html += "<div><span>これまでの自己ベスト</span><b>" + state.prevBest.toFixed(1) + "%</b></div>";
      }
      html += '<div><span>1問ごと（◎2%以内 ○5%以内 △10%以内 ×それ以上）</span><b class="marks">' +
        h.map(function (x) { return errorMark(x.diff); }).join("") + "</b></div>";
    } else {
      var ok = h.filter(function (x) { return x.correct; }).length;
      html += "<div><span>回答</span><b>" + h.length + "問</b></div><div><span>正解</span><b>" + ok + "問</b></div>";
      if (h.length) html += "<div><span>正答率</span><b>" + Math.round(ok / h.length * 100) + "%</b></div>";
    }
    html += "</div>";
    if (h.length) {
      html += '<div class="table-wrap"><table><thead><tr><th>#</th><th>攻撃側</th><th>技</th><th>防御側</th><th class="n">正解</th>' +
        (state.mode === "easy" ? "<th>結果</th>" : '<th class="n">回答</th><th class="n">誤差</th>') + "</tr></thead><tbody>";
      h.forEach(function (x, i) {
        html += '<tr><td class="n">' + (i + 1) + "</td><td>" + esc(x.attacker) + "</td><td>" + esc(x.move) + "</td><td>" + esc(x.defender) +
          '</td><td class="n">' + pct(x.answer) + "</td>" +
          (state.mode === "easy" ? "<td>" + (x.correct ? "正解" : "不正解") + "</td>"
            : '<td class="n">' + pct(x.guess) + '</td><td class="n">' + x.diff.toFixed(1) + "%</td>") + "</tr>";
      });
      html += "</tbody></table></div>";
    }
    if (state.mode === "challenge" && h.length) html += renderShare();
    html += '<div class="actions"><button class="btn" type="button" id="again">もう一度</button>' +
      '<button class="btn ghost" type="button" data-title>タイトルへ</button></div></section>';
    return html;
  }

  function render() {
    renderStatus();
    if (state.title) {
      $main.innerHTML = renderTitle();
    } else if (state.finished) {
      $main.innerHTML = renderSummary();
    } else {
      $main.innerHTML = renderBattle(state.q) + renderAnswer(state.q) + (state.answered ? renderResult(state.q) : "");
    }
    bind();
  }

  function bind() {
    $main.querySelectorAll("[data-start]").forEach(function (b) {
      b.addEventListener("click", function () { setMode(b.dataset.start); });
    });
    $main.querySelectorAll("[data-title]").forEach(function (b) { b.addEventListener("click", goTitle); });
    $main.querySelectorAll("[data-choice]").forEach(function (b) {
      b.addEventListener("click", function () { submitChoice(+b.dataset.choice); });
    });
    var form = document.getElementById("guess-form");
    if (form) form.addEventListener("submit", function (e) { e.preventDefault(); submitNumber(); });
    var nextBtn = document.getElementById("next");
    if (nextBtn) { nextBtn.addEventListener("click", next); nextBtn.focus({ preventScroll: true }); }
    var quit = document.getElementById("quit");
    if (quit) quit.addEventListener("click", finish);
    var again = document.getElementById("again");
    if (again) again.addEventListener("click", function () { setMode(state.mode); });
    var copy = document.getElementById("share-copy");
    if (copy) copy.addEventListener("click", copyShare);
    var nat = document.getElementById("share-native");
    if (nat) nat.addEventListener("click", function () {
      navigator.share({ title: "ダメージ感覚", text: shareText(), url: SITE_URL }).catch(function () { /* キャンセル時は何もしない */ });
    });
  }

  document.querySelectorAll(".modes button").forEach(function (b) {
    b.addEventListener("click", function () { setMode(b.dataset.mode); });
  });
  document.addEventListener("keydown", function (e) {
    if (e.target.tagName === "INPUT" || e.metaKey || e.ctrlKey || e.altKey) return;
    if (!state.title && !state.finished && !state.answered && state.mode === "easy" && /^[1-4]$/.test(e.key)) submitChoice(+e.key - 1);
  });

  var snap = data.snapshot;
  if (snap) {
    document.getElementById("snapshot").textContent = "シーズン" + snap.snapshot_id.replace("_single", "") + " シングル使用率上位50（" + snap.date + "取得）";
    document.getElementById("source").textContent = snap.source_url;
  }
  document.getElementById("home").addEventListener("click", goTitle);
  render();
})();
