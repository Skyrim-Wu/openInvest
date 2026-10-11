"""从 ../scripts/index.html 生成 QMuse 版的 src/page.css、src/body.html、src/logic.js。

演示页只维护 index.html 一份；改完跑 `python3 sync.py` 再 `qmuse import .`。
body.html 是静态标记（模型文本仍走 textContent）；logic.js 把原脚本包进 init(API)，
相对路径 /api/ 改成 ${API}/api/。
"""
import re
from pathlib import Path

here = Path(__file__).resolve().parent
src = (here.parent / "scripts" / "index.html").read_text(encoding="utf-8")
css = re.search(r"<style>(.*?)</style>", src, re.S).group(1)
body = re.search(r"<main>.*?</main>", src, re.S).group(0)
js = re.search(r"<script>(.*?)</script>", src, re.S).group(1)
js2 = js.replace("fetch(`/api/", "fetch(`${API}/api/").replace('fetch("/api/', 'fetch(API + "/api/')
assert js2.count("${API}/api/") + js2.count('API + "/api/') == js.count("/api/"), "有未改写的 /api/ 调用"
(here / "src" / "page.css").write_text(css.strip() + "\n", encoding="utf-8")
(here / "src" / "body.html").write_text(body + "\n", encoding="utf-8")
(here / "src" / "logic.js").write_text(
    "// 由 sync.py 从 ../scripts/index.html 生成，勿手改\nexport function init(API) {\n" + js2 + "\n}\n",
    encoding="utf-8")
print("synced")
