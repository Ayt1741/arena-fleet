#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SEEK — общий разбор выдачи поисковиков (ход 53).

Почему отдельный файл: в ходе 52 все 157 запросов флота вернули пусто —
DuckDuckGo отдаёт страницу-заглушку. Здесь четыре движка и разбор каждого:

  bing      — ссылка в редиректе bing.com/ck/a?u=a1<base64>; декодируем
  ddg-html  — result__a + result__snippet; ссылка в uddg=; декодируем
  ddg-lite  — result-link + result-snippet; ссылка в uddg=; декодируем
  marginalia — обычные <a href="http..."> внутри секций

Все запросы — настоящие HTTP-запросы, ответ пишется построчно.
"""
import base64
import html as html_mod
import os
import re
import time
import urllib.parse
import urllib.request

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/126.0.0.0 Safari/537.36')

ДВИЖКИ = [
    ('bing', 'https://www.bing.com/search?q='),
    ('ddg-html', 'https://html.duckduckgo.com/html/?q='),
    ('ddg-lite', 'https://lite.duckduckgo.com/lite/?q='),
    ('marginalia', 'https://search.marginalia.nu/search?query='),
]

ЗАГОЛОВКИ = {'user-agent': UA, 'accept-language': 'en-US,en;q=0.9',
             'accept': 'text/html,application/xhtml+xml'}


def чисто(текст):
    t = re.sub(r'<[^>]+>', ' ', текст or '')
    t = html_mod.unescape(t)
    return re.sub(r'\s+', ' ', t).strip()


def раз_uddg(url):
    """DuckDuckGo: /l/?uddg=<urlencoded>."""
    m = re.search(r'uddg=([^&]+)', url or '')
    if m:
        return urllib.parse.unquote(m.group(1))
    if url and url.startswith('//'):
        return 'https:' + url
    return url


def раз_bing(url):
    """Bing: /ck/a?...&u=a1<base64url>."""
    m = re.search(r'[?&]u=a1([A-Za-z0-9_\-]+)', url or '')
    if m:
        s = m.group(1)
        s += '=' * (-len(s) % 4)
        try:
            return base64.urlsafe_b64decode(s).decode('utf-8', 'replace')
        except Exception:
            pass
    return url


def разбор_bing(h):
    out = []
    for блок in re.findall(r'<li class="b_algo".*?</li>', h, re.S)[:8]:
        m = re.search(r'<h2>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', блок, re.S)
        if not m:
            continue
        out.append({'title': чисто(m.group(2))[:180],
                    'url': раз_bing(html_mod.unescape(m.group(1))),
                    'snippet': чисто(блок)[:400]})
    return out


def разбор_ddg_html(h):
    out = []
    блоки = re.split(r'<div class="result results_links', h)
    for блок in блоки[1:9]:
        a = re.search(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', блок, re.S)
        if not a:
            continue
        sn = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', блок, re.S)
        out.append({'title': чисто(a.group(2))[:180],
                    'url': раз_uddg(html_mod.unescape(a.group(1))),
                    'snippet': чисто(sn.group(1))[:400] if sn else ''})
    return out


def разбор_ddg_lite(h):
    out = []
    for блок in re.split(r'<tr>\s*<td class="result-link"', h)[1:9]:
        a = re.search(r'href="([^"]+)"[^>]*>(.*?)</a>', блок, re.S)
        if not a:
            continue
        sn = re.search(r'class=\'result-snippet\'>(.*?)</td>', блок, re.S)
        out.append({'title': чисто(a.group(2))[:180],
                    'url': раз_uddg(html_mod.unescape(a.group(1))),
                    'snippet': чисто(sn.group(1))[:400] if sn else ''})
    return out


def разбор_marginalia(h):
    out = []
    for блок in re.findall(r'<section class="search-result".*?</section>', h, re.S)[:8]:
        m = re.search(r'href="(https?://[^"]+)"', блок)
        t = re.search(r'<h2>(.*?)</h2>', блок, re.S)
        if m:
            out.append({'title': чисто(t.group(1))[:180] if t else m.group(1),
                        'url': m.group(1), 'snippet': чисто(блок)[:400]})
    if not out:
        for блок in re.findall(r'<article.*?</article>', h, re.S)[:8]:
            m = re.search(r'href="(https?://[^"]+)"', блок)
            if m:
                out.append({'title': m.group(1), 'url': m.group(1), 'snippet': чисто(блок)[:400]})
    return out


РАЗБОР = {'bing': разбор_bing, 'ddg-html': разбор_ddg_html,
          'ddg-lite': разбор_ddg_lite, 'marginalia': разбор_marginalia}


def искать(q, движки=None):
    """Опрашивает ВСЕ движки и берёт лучшие ссылки.

    Один движок даёт слабую выдачу (Bing местами отдаёт «общие» страницы),
    поэтому берём два движка и сливаем: уникальные домены, до 8 ссылок.
    Возвращает {'engine': 'движки', 'hits': [...]}.
    """
    собраны = []
    домены = set()
    взятый_движок = None
    for имя, база in (движки or ДВИЖКИ):
        for попытка in range(2):
            try:
                r = urllib.request.Request(база + urllib.parse.quote(q), headers=ЗАГОЛОВКИ)
                h = urllib.request.urlopen(r, timeout=35).read().decode('utf-8', 'replace')
                hits = РАЗБОР[имя](h)
                if hits:
                    if взятый_движок is None:
                        взятый_движок = имя
                    for hit in hits:
                        домен = urllib.parse.urlparse(hit['url']).netloc
                        if домен and домен in домены:
                            continue
                        домены.add(домен)
                        hit['engine'] = имя
                        собраны.append(hit)
                    break
            except Exception:
                time.sleep(2 * (попытка + 1))
    return {"engine": взятый_движок, 'hits': собраны[:8]}


def числа(текст, максимум=12):
    """Строки выдачи, где есть числа — это и есть факты для цитаты."""
    out = []
    for строка in re.split(r'[\n|·•]', текст or ''):
        строка = строка.strip()
        if not строка or len(строка) > 200:
            continue
        if re.search(r'\d{1,3}[.,]\d|\b\d{2,4}\b', строка):
            out.append(строка[:200])
        if len(out) >= максимум:
            break
    return out
