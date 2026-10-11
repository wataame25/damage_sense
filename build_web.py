"""web/src のテンプレートに data/*.json と engine.js を埋め込み、1ファイルで動く web/index.html を作る。

    python3 build_web.py
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "web" / "src"
OUT = ROOT / "web" / "index.html"
TABLES = ["pokemon", "moves", "abilities", "items", "weather", "field", "ev_rules", "usage_snapshot"]


def data_js():
    data = {t: json.loads((ROOT / "data" / f"{t}.json").read_text(encoding="utf-8")) for t in TABLES}
    # </script> を含まないよう "/" をエスケープ
    return "var GAME_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/") + ";"


def render():
    """テンプレートにデータ・エンジン・画面ロジックを埋め込んだHTML断片（<html>等の外枠なし）"""
    html = (SRC / "index.html").read_text(encoding="utf-8")
    for marker, content in [("/*__DATA__*/", data_js()),
                            ("/*__ENGINE__*/", (SRC / "engine.js").read_text(encoding="utf-8")),
                            ("/*__APP__*/", (SRC / "app.js").read_text(encoding="utf-8"))]:
        assert html.count(marker) == 1, marker
        html = html.replace(marker, content)
    return html


def build():
    OUT.write_text('<!doctype html>\n<html lang="ja">\n' + render() + "\n</html>\n", encoding="utf-8")
    return OUT


if __name__ == "__main__":
    print(f"wrote {build()}")
