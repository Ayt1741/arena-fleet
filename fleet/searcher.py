#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ПОИСК НА МАШИНЕ ФЛОТА: каждая машина ищет свою порцию запросов в интернете.

Каждый запрос — настоящий запрос к поисковику (DuckDuckGo), ответ пишется строкой
в JSON. Машина получает свой список запросов (по слайсу общего файла) — поэтому
20 машин делят 157 запросов, и ни один IP не упирается в лимит.

  SLOT=1 python3 fleet/searcher.py
Результат: search-<slot>.json со списком {q, title, url}.
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

SLOT = int(os.environ.get('SLOT', '1'))
ВСЕГО_МАШИН = int(os.environ.get('SLOTS', '20'))
ФАЙЛ_ЗАПРОСОВ = os.environ.get('QUERIES', 'fleet/queries-52.txt')
ВЫХОД = os.environ.get('OUT', 'search-%02d.json' % SLOT)
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/126.0.0.0 Safari/537.36')
БАЗЫ = ("https://html.duckduckgo.com/html/?q=", "https://lite.duckduckgo.com/lite/?q=")


def log(r):
    print(json.dumps(r, ensure_ascii=False), flush=True)


def запросы():
    out = []
    with open(ФАЙЛ_ЗАПРОСОВ, encoding="utf-8") as f:
        for s in f:
            s = s.strip()
            if s and not s.startswith("#"):
                out.append(s)
    return out


def искать(q):
    for база in БАЗЫ:
        for попытка in range(3):
            try:
                r = urllib.request.Request(база + urllib.parse.quote(q),
                                           headers={'user-agent': UA,
                                                    'accept-language': 'en-US,en;q=0.9'})
                h = urllib.request.urlopen(r, timeout=40).read().decode("utf-8", "replace")
                t = re.findall(r'class="result__a"[^>]*>(.*?)</a>', h, re.S)
                u = re.findall(r'class="result__url"[^>]*>(.*?)</a>', h, re.S)
                if not t:
                    t = re.findall(r'class="result-link"[^>]*>(.*?)</a>', h, re.S)
                    u = re.findall(r'class="result-link"[^>]*href="([^"]+)"', h, re.S)
                if t:
                    заг = re.sub(r"<[^>]+>", "", t[0]).strip()
                    заг = заг.replace("&amp;", "&").replace("&#x27;", "'").replace("&quot;", '"')
                    дом = ""
                    if u:
                        дом = re.sub(r"<[^>]+>", "", u[0]).strip()[:60]
                    return {"q": q, "title": заг[:150], "url": дом, "ok": True}
            except Exception:
                time.sleep(3 * (попытка + 1))
    return {"q": q, "title": "", "url": "", "ok": False}


def main():
    все = запросы()
    мои = [q for i, q in enumerate(все) if i % ВСЕГО_МАШИН == (SLOT - 1) % ВСЕГО_МАШИН]
    log({"event": "start", "slot": SLOT, "total": len(все), "mine": len(мои)})
    результат = []
    for i, q in enumerate(мои, 1):
        результат.append(искать(q))
        if i % 3 == 0:
            log({"event": "progress", "slot": SLOT, "done": i, "of": len(мои)})
        time.sleep(1.5)
    json.dump({"slot": SLOT, "results": результат}, open(ВЫХОД, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    удалось = sum(1 for r in результат if r["ok"])
    log({"event": "finish", "slot": SLOT, "done": len(результат), "ok": удалось})


if __name__ == "__main__":
    main()
