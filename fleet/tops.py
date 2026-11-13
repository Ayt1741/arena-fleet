#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""АГЕНТ «ТОПЫ ВСЕХ БЕНЧМАРКОВ» — отдельный агент (требование пользователя, ход 53).

Задача: снять лучшие модели не только по LM Arena, а по всем бенчмаркам кода
и рассуждений, и вернуть не «мнение», а числа со ссылками.

Что делает машина:
  1) берёт свой список бенчмарков (слайс общей таблицы по номеру слота);
  2) по каждому делает несколько РЕАЛЬНЫХ запросов к поисковику (Bing + DDG-lite
     + Marginalia — те, что отвечают; DuckDuckGo отдаёт заглушку, поэтому
     он только в запасном порядке);
  3) вытаскивает из выдачи строки с моделями и числами (score/place);
  4) пишет tops-<slot>.json: запрос → заголовок → url → что дало.

Артефакт: tops-<slot>.json (и вариант markdown-выжимки).
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

SLOT = int(os.environ.get('SLOT', '1'))
ВСЕГО = int(os.environ.get('SLOTS', '30'))
ВЫХОД = os.environ.get('OUT', 'tops-%02d.json' % SLOT)
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/126.0.0.0 Safari/537.36')

# Бенчмарки: код, агенты, рассуждение, длинный контекст, фронтенд.
БЕНЧМАРКИ = [
    ('Terminal-Bench 4.0 leaderboard', 'terminal bench 4.0 leaderboard models scores'),
    ('Terminal-Bench 2.1 leaderboard', 'terminal bench 2.1 leaderboard model scores'),
    ('SWE-bench Pro leaderboard', 'swe bench pro leaderboard model ranking 2026'),
    ('SWE-bench Verified leaderboard', 'swe bench verified leaderboard top models'),
    ('SWE-bench Multilingual leaderboard', 'swe bench multilingual leaderboard models'),
    ('DeepSWE leaderboard', 'deepswe benchmark leaderboard model scores'),
    ('SWE-Atlas leaderboard', 'swe atlas codebase leaderboard models'),
    ('LiveCodeBench leaderboard', 'livecodebench leaderboard 2026 models'),
    ('CursorBench leaderboard', 'cursorbench leaderboard model ranking'),
    ('FrontierCode leaderboard', 'frontiercode benchmark leaderboard models'),
    ('Vals RSI leaderboard', 'vals rsi leaderboard coding models'),
    ('AA Coding Agents Index', 'artificial analysis coding agents index ranking'),
    ('AA Intelligence Index', 'artificial analysis intelligence index ranking models'),
    ('Artificial Analysis price per task', 'artificial analysis price per task coding models'),
    ('Code Arena WebDev leaderboard', 'arena ai webdev leaderboard models elo'),
    ('Arena Code leaderboard', 'lmarena code leaderboard models 2026'),
    ('Design Arena leaderboard', 'design arena leaderboard web design models elo'),
    ('WebDev Arena top models', 'webdev arena top models november 2026'),
    ('Humanitys Last Exam leaderboard', 'humanitys last exam verified leaderboard models'),
    ('GPQA leaderboard', 'gpqa diamond leaderboard models score'),
    ('CritPt leaderboard', 'critpt leaderboard reasoning models'),
    ('IMOAnswerBench leaderboard', 'imoanswerbench leaderboard models'),
    ('HMMT leaderboard', 'hmmt 2026 leaderboard models'),
    ('FrontierSWE v2 leaderboard', 'frontierswe v2 leaderboard models score'),
    ('MRCR long context leaderboard', 'mrcr benchmark long context leaderboard models'),
    ('GraphWalks long context', 'graphwalks benchmark long context models score'),
    ('OSWorld leaderboard', 'osworld leaderboard computer use models'),
    ('GDPval leaderboard', 'gdpval leaderboard models elo 2026'),
    ('AutomationBench leaderboard', 'automationbench leaderboard agent models'),
    ('ExploitBench leaderboard', 'exploitbench leaderboard models security'),
    ('Bug Hunt Bench leaderboard', 'bug hunt bench leaderboard models fix rate'),
    ('AA Long Context Understanding', 'artificial analysis long context understanding benchmark models'),
    ('SimpleQA verified leaderboard', 'simpleqa verified leaderboard models accuracy'),
    ('BrowseComp leaderboard', 'browsecomp leaderboard models score'),
    ('Arc AGI 2 leaderboard', 'arc agi 2 leaderboard models'),
    ('Aider polyglot leaderboard', 'aider polyglot leaderboard models'),
    ('BigCodeBench leaderboard', 'bigcodebench leaderboard models'),
    ('Arena text leaderboard top 10', 'lmarena text leaderboard top 10 models elo'),
    ('Gemini 4 Argon benchmarks', 'gemini 4 argon benchmark scores deepswe graphwalks'),
    ('Claude Sonnet 5.5 benchmarks', 'claude sonnet 5.5 benchmark terminal bench swe bench pro'),
    ('Claude Opus 5.5 benchmarks', 'claude opus 5.5 benchmark swe bench pro terminal bench'),
    ('Muse Wonder benchmark', 'muse wonder benchmark coding index deepswe terminal bench'),
    ('Muse Spark 1.3 benchmark', 'muse spark 1.3 benchmark terminal bench mrcr'),
    ('GPT-6 Sol Luna Astra benchmark', 'gpt 6 sol luna astra benchmark coding index'),
    ('Grok 4.6 benchmark', 'grok 4.6 benchmark coding index terminal bench'),
    ('Fable 5.2 benchmark', 'claude fable 5.2 benchmark leaderboard'),
    ('Kimi K3 benchmark', 'kimi k3 benchmark code arena context length'),
    ('Flash 3.8 benchmark', 'gemini 3.8 flash benchmark deepswe terminal bench'),
    ('model context window 1M leaderboard', 'longest context window models 1 million tokens leaderboard'),
    ('best open weight vs closed model 2026', 'best coding model 2026 benchmark top'),
    ('AI coding agent benchmark ranking 2026', 'best ai model for coding 2026 benchmark ranking'),
]

ДВИЖКИ = [
    ('bing', 'https://www.bing.com/search?q='),
    ('ddg-lite', 'https://lite.duckduckgo.com/lite/?q='),
    ('marginalia', 'https://search.marginalia.nu/search?query='),
    ('ddg-html', 'https://html.duckduckgo.com/html/?q='),
]


def log(r):
    print(json.dumps(r, ensure_ascii=False), flush=True)


def разобрать_bing(html):
    out = []
    for блок in re.findall(r'<li class="b_algo".*?</li>', html, re.S)[:6]:
        m = re.search(r'<h2><a href="([^"]+)"[^>]*>(.*?)</a>', блок, re.S)
        if not m:
            continue
        заг = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        сниппет = re.sub(r'<[^>]+>', ' ', блок)
        сниппет = re.sub(r'\s+', ' ', сниппет).strip()[:400]
        out.append({'title': заг[:180], 'url': m.group(1), 'snippet': сниппет})
    return out


def разобрать_lite(html):
    out = []
    for заг, url in zip(re.findall(r'class="result-link"[^>]*>(.*?)</a>', html, re.S),
                         re.findall(r'class="result-link"[^>]*href="([^"]+)"', html, re.S)):
        out.append({'title': re.sub(r'<[^>]+>', '', заг).strip()[:180], 'url': url, 'snippet': ''})
    return out


def разобрать_marginalia(html):
    out = []
    for блок in re.findall(r'<div class="card[^"]*".*?</div>\s*</div>', html, re.S)[:6]:
        m = re.search(r'href="(https?://[^"]+)"', блок)
        t = re.search(r'<h2>(.*?)</h2>', блок, re.S)
        if m:
            out.append({'title': re.sub(r'<[^>]+>', '', t.group(1)).strip()[:180] if t else m.group(1),
                        'url': m.group(1),
                        'snippet': re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', блок)).strip()[:400]})
    return out


def разобрать_ddg(html):
    out = []
    for заг, url in zip(re.findall(r'class="result__a"[^>]*>(.*?)</a>', html, re.S),
                         re.findall(r'class="result__url"[^>]*>(.*?)</a>', html, re.S)):
        out.append({'title': re.sub(r'<[^>]+>', '', заг).strip()[:180],
                    'url': re.sub(r'<[^>]+>', '', url).strip()[:200], 'snippet': ''})
    return out


РАЗБОР = {'bing': разобрать_bing, 'ddg-lite': разобрать_lite,
          'marginalia': разобрать_marginalia, 'ddg-html': разобрать_ddg}


def искать(запрос):
    for имя, база in ДВИЖКИ:
        for попытка in range(2):
            try:
                r = urllib.request.Request(база + urllib.parse.quote(запрос),
                                           headers={'user-agent': UA, 'accept-language': 'en-US,en;q=0.9',
                                                    'accept': 'text/html,application/xhtml+xml'})
                html = urllib.request.urlopen(r, timeout=35).read().decode('utf-8', 'replace')
                hits = РАЗБОР[имя](html)
                if hits:
                    return {'engine': имя, 'hits': hits, 'bytes': len(html)}
            except Exception:
                time.sleep(2 * (попытка + 1))
    return {'engine': None, 'hits': [], 'bytes': 0}


def числа(текст):
    """Из текста выдачи — пары «модель ~ число»."""
    out = []
    for строка in re.split(r'[\n|·]', текст):
        строка = строка.strip()
        if not строка or len(строка) > 160:
            continue
        if re.search(r'\d{1,3}[.,]\d|\b\d{2,4}\b', строка):
            out.append(строка[:160])
    return out[:12]


def main():
    мои = [б for i, б in enumerate(БЕНЧМАРКИ) if i % ВСЕГО == (SLOT - 1) % ВСЕГО]
    log({'event': 'start', 'slot': SLOT, 'total_benchmarks': len(БЕНЧМАРКИ), 'mine': len(мои)})
    результат = []
    запросов = 0
    for имя, ключевые in мои:
        вопросы = [ключевые,
                   ключевые + ' top 10 table',
                   ключевые + ' scores 2026 comparison']
        for q in вопросы:
            ответ = искать(q)
            запросов += 1
            строки = []
            for h in ответ['hits'][:3]:
                строки.extend(числа(h.get('snippet', '')))
            результат.append({'benchmark': имя, 'query': q, 'engine': ответ['engine'],
                               'hits': ответ['hits'][:4], 'facts': строки[:10]})
            log({'event': 'query', 'n': запросов, 'q': q[:70], 'engine': ответ['engine'],
                 'hits': len(ответ['hits']), 'facts': len(строки)})
            time.sleep(1.2)
    json.dump({'slot': SLOT, 'queries': запросов, 'results': результат},
              open(ВЫХОД, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    с_данными = sum(1 for r in результат if r['facts'])
    log({'event': 'finish', 'queries': запросов, 'with_facts': с_данными, 'out': ВЫХОД})


if __name__ == '__main__':
    main()
