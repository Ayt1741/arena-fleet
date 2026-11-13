#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ПОИСК ФЛОТА, версия 2 (ход 53).

Почему новая: DuckDuckGo отдаёт страницу-заглушку (0 результатов на 157
запросах в ходе 52). Теперь движков четыре, и берётся первый, что дал ссылки:
bing → ddg-lite → marginalia → ddg-html. Каждый запрос — настоящий запрос,
ответ пишется построчно (чтобы не потерять результат при таймауте).

  SLOT=1 SLOTS=20 QUERIES=fleet/queries-53.txt OUT=search-01.json python3 fleet/searcher2.py
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

SLOT = int(os.environ.get('SLOT', '1'))
ВСЕГО = int(os.environ.get('SLOTS', '20'))
ФАЙЛ = os.environ.get('QUERIES', 'fleet/queries-53.txt')
ВЫХОД = os.environ.get('OUT', 'search-%02d.json' % SLOT)
ПОСТРОЧНО = os.environ.get('STREAM', 'search-%02d.jsonl' % SLOT)
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/126.0.0.0 Safari/537.36')

ДВИЖКИ = [
    ('bing', 'https://www.bing.com/search?q='),
    ('ddg-lite', 'https://lite.duckduckgo.com/lite/?q='),
    ('marginalia', 'https://search.marginalia.nu/search?query='),
    ('ddg-html', 'https://html.duckduckgo.com/html/?q='),
]


def log(r):
    print(json.dumps(r, ensure_ascii=False), flush=True)


def разбор_ bing(html):
    out = []
    for блок in re.findall(r'<li class="b_algo".*?</li>', html, re.S)[:6]:
        m = re.search(r'<h2><a href="([^"]+)"[^>]*>(.*?)</a>', блок, re.S)
        if not m:
            continue
        out.append({'title': re.sub(r'<[^>]+>', '', m.group(2)).strip()[:180],
                    'url': m.group(1),
                    'snippet': re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', блок)).strip()[:400]})
    return out


def разбор_lite(html):
    out = []
    for заг, url in zip(re.findall(r'class="result-link"[^>]*>(.*?)</a>', html, re.S),
                         re.findall(r'class="result-link"[^>]*href="([^"]+)"', html, re.S)):
        out.append({'title': re.sub(r'<[^>]+>', '', заг).strip()[:180], 'url': url, 'snippet': ''})
    return out


def разбор_marginalia(html):
    out = []
    for блок in re.findall(r'<section class="search-result".*?</section>', html, re.S)[:6]:
        m = re.search(r'href="(https?://[^"]+)"', блок)
        t = re.search(r'<h2>(.*?)</h2>', блок, re.S)
        if m:
            out.append({'title': re.sub(r'<[^>]+>', '', t.group(1)).strip()[:180] if t else m.group(1),
                        'url': m.group(1),
                        'snippet': re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', блок)).strip()[:400]})
    return out


def разбор_ddg(html):
    out = []
    for заг, url in zip(re.findall(r'class="result__a"[^>]*>(.*?)</a>', html, re.S),
                         re.findall(r'class="result__url"[^>]*>(.*?)</a>', html, re.S)):
        out.append({'title': re.sub(r'<[^>]+>', '', заг).strip()[:180],
                    'url': re.sub(r'<[^>]+>', '', url).strip()[:200], 'snippet': ''})
    return out


РАЗБОР = {'bing': разбор_ bing, 'ddg-lite': разбор_lite,
          'marginalia': разбор_marginalia, 'ddg-html': разбор_ddg}


def искать(q):
    for имя, база in ДВИЖКИ:
        for попытка in range(2):
            try:
                r = urllib.request.Request(база + urllib.parse.quote(q),
                                           headers={'user-agent': UA,
                                                    'accept-language': 'en-US,en;q=0.9',
                                                    'accept': 'text/html,application/xhtml+xml'})
                html = urllib.request.urlopen(r, timeout=35).read().decode('utf-8', 'replace')
                hits = РАЗБОР[имя](html)
                if hits:
                    return {'engine': имя, 'hits': hits}
            except Exception:
                time.sleep(2 * (попытка + 1))
    return {'engine': None, 'hits': []}


def main():
    все = []
    with open(ФАЙЛ, encoding='utf-8') as f:
        for s in f:
            s = s.strip()
            if s and not s.startswith('#'):
                все.append(s)
    мои = [q for i, q in enumerate(все) if i % ВСЕГО == (SLOT - 1) % ВСЕГО]
    log({'event': 'start', 'slot': SLOT, 'total': len(все), 'mine': len(мои)})
    результат = []
    поток = open(ПОСТРОЧНО, 'w', encoding='utf-8')
    for i, q in enumerate(мои, 1):
        r = искать(q)
        запись = {'q': q, 'engine': r['engine'], 'hits': r['hits'][:4],
                  'ok': bool(r['hits'])}
        результат.append(запись)
        поток.write(json.dumps(запись, ensure_ascii=False) + '\n')
        поток.flush()
        log({'event': 'query', 'n': i, 'of': len(мои), 'q': q[:70],
             'engine': r['engine'], 'hits': len(r['hits'])})
        time.sleep(1.3)
    поток.close()
    json.dump({'slot': SLOT, 'results': результат}, open(ВЫХОД, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    log({'event': 'finish', 'done': len(результат),
         'ok': sum(1 for r in результат if r['ok'])})


if __name__ == '__main__':
    main()
