#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""АГЕНТ «ТОПЫ ПО ВСЕМ БЕНЧМАРКАМ» — отдельный агент (требование пользователя, ход 53).

Задача от пользователя: «Топы нужны не только LM Arena, а в принципе всех
бенчмарков, и я сказал тебе дать эту задачу агенту отдельному».

Как работает (30 машин, у каждой свой срез):
  1) с каждой страницы leaderboard'а берётся НАСТОЯЩАЯ таблица (строки <tr>),
     а не текст поисковой выдачи: benchlm.ai и llm-stats.com отдают таблицы
     целиком, в них есть модели, места и проценты;
  2) по каждой теме делаются ещё и реальные поисковые запросы (4 движка) —
     чтобы видеть и источники, которых нет в таблицах;
  3) всё пишется в tops-<slot>.json: страница → строка таблицы → факт.

Артефакт: tops-<slot>.json
"""
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from seek import искать, числа

SLOT = int(os.environ.get('SLOT', '1'))
ВСЕГО = int(os.environ.get('SLOTS', '30'))
ВЫХОД = os.environ.get('OUT', 'tops-%02d.json' % SLOT)
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/126.0.0.0 Safari/537.36')

# Наши 14 моделей — чтобы вытаскивать именно их строки из чужих таблиц.
НАШИ = ['Sonnet 5.5', 'Opus 5.5', 'Haiku 5.5', 'Fable 5', 'Muse Spark', 'Muse Wonder',
        'Muse Ember', 'Argon', 'Gemini 3.8 Flash', 'GPT-6', 'Sol', 'Luna', 'Astra',
        'Terra', 'Grok 4.6', 'Kimi', 'Flash']

# Страницы: (имя, url, поисковый запрос)
СТРАНИЦЫ = [
    ('Terminal-Bench 4.0', 'https://llm-stats.com/benchmarks/terminal-bench-4.0',
     'terminal bench 4.0 leaderboard models scores'),
    ('SWE-bench Pro', 'https://llm-stats.com/benchmarks/swe-bench-pro',
     'swe bench pro leaderboard models 2026'),
    ('SWE-bench Verified', 'https://llm-stats.com/benchmarks/swe-bench-verified',
     'swe bench verified leaderboard models'),
    ('LiveCodeBench', 'https://llm-stats.com/benchmarks/livecodebench',
     'livecodebench leaderboard models scores'),
    ('GPQA', 'https://llm-stats.com/benchmarks/gpqa', 'gpqa leaderboard models score'),
    ('AA-LCR', 'https://llm-stats.com/benchmarks/aa-lcr', 'artificial analysis lcr leaderboard models'),
    ('AIME 2025', 'https://llm-stats.com/benchmarks/aime-2025', 'aime 2025 leaderboard models'),
    ('HumanEval', 'https://llm-stats.com/benchmarks/humaneval', 'humaneval leaderboard models'),
    ('MMLU-Pro', 'https://llm-stats.com/benchmarks/mmlu-pro', 'mmlu pro leaderboard models'),
    ('MMMU-Pro', 'https://llm-stats.com/benchmarks/mmmu-pro', 'mmmu pro leaderboard models'),
    ('MCP Atlas', 'https://llm-stats.com/benchmarks/mcp-atlas', 'mcp atlas benchmark leaderboard models'),
    ('Terminal-Bench (benchlm)', 'https://benchlm.ai/benchmarks/terminal-bench',
     'terminal bench leaderboard full table'),
    ('Terminal-Bench Hard', 'https://benchlm.ai/benchmarks/terminal-bench-hard',
     'terminal bench hard leaderboard models'),
    ('DeepSWE', 'https://benchlm.ai/benchmarks/deepswe', 'deepswe leaderboard models scores'),
    ('DeepSWE 1.1', 'https://benchlm.ai/benchmarks/mercordeepresearchbench2',
     'deepswe leaderboard score models'),
    ('FrontierSWE v2', 'https://benchlm.ai/benchmarks/frontierswev2', 'frontierswe v2 leaderboard models'),
    ('CursorBench', 'https://benchlm.ai/benchmarks/cursorbench', 'cursorbench leaderboard models'),
    ('FrontierCode', 'https://benchlm.ai/benchmarks/frontiercode', 'frontiercode leaderboard models'),
    ('FrontierCode 2.0', 'https://benchlm.ai/benchmarks/aafrontiercode2',
     'frontiercode 2.0 leaderboard models effort levels'),
    ('AA Coding Agents', 'https://benchlm.ai/benchmarks/aacodingagents',
     'artificial analysis coding agents index leaderboard'),
    ('AA Coding Index', 'https://benchlm.ai/benchmarks/aacodingindex', 'aa coding index leaderboard models'),
    ('AA Agentic Index', 'https://benchlm.ai/benchmarks/aaagenticindex', 'aa agentic index leaderboard models'),
    ('MRCR 512K-1M', 'https://benchlm.ai/benchmarks/mrcr-v2-512k-1m', 'mrcr 512k 1m long context leaderboard'),
    ('MRCR 1M', 'https://benchlm.ai/benchmarks/mrcr1m', 'mrcr 1m context models leaderboard'),
    ('GraphWalks 256K-1M', 'https://benchlm.ai/benchmarks/graphwalks-bfs-256k-1m',
     'graphwalks long context leaderboard models'),
    ('OSWorld 2.1', 'https://benchlm.ai/benchmarks/osworld-2-1', 'osworld 2.1 leaderboard computer use models'),
    ('GDPval-AA', 'https://benchlm.ai/benchmarks/gdpvalaa', 'gdpval aa leaderboard elo models'),
    ('AA AutomationBench', 'https://benchlm.ai/benchmarks/aaautomationbench',
     'automation bench leaderboard agent models'),
    ('ExploitBench', 'https://benchlm.ai/benchmarks/exploitbench', 'exploit bench leaderboard models'),
    ('Bug Hunt Bench', 'https://benchlm.ai/benchmarks/bug-hunt-bench', 'bug hunt bench leaderboard fix rate models'),
    ('SWE-Atlas Codebase QnA', 'https://benchlm.ai/benchmarks/mercorsweatlasqna',
     'swe atlas codebase qna leaderboard models'),
    ('Design Arena WebDev', 'https://benchlm.ai/benchmarks/designarenaagenticwebdev',
     'design arena agentic webdev leaderboard models'),
    ('ARC-AGI 3', 'https://benchlm.ai/benchmarks/arcagi3', 'arc agi 3 leaderboard models'),
    ('LiveCodeBench (benchlm)', 'https://benchlm.ai/benchmarks/livecodebench',
     'livecodebench leaderboard benchlm models'),
    ('SWE-bench Pro (benchlm)', 'https://benchlm.ai/benchmarks/swebenchpro',
     'swe bench pro benchlm leaderboard'),
    ('Humanity Last Exam', 'https://benchlm.ai/benchmarks/aahumanityslastexam',
     'humanitys last exam leaderboard models score'),
    ('AA OmniScience', 'https://benchlm.ai/benchmarks/aaomniscienceindex',
     'aa omniscience index leaderboard models'),
    ('AA-LCR (benchlm)', 'https://benchlm.ai/benchmarks/aalcr', 'aa lcr long context reasoning leaderboard'),
    ('Terminal-Bench 4.1', 'https://benchlm.ai/benchmarks/terminalbench41',
     'terminal bench 4.1 leaderboard models'),
    ('Valves RSI', 'https://benchlm.ai/benchmarks/valsrsi', 'vals rsi leaderboard coding models'),
    ('FrontierCode 1.1', 'https://benchlm.ai/benchmarks/frontiercode11extended',
     'frontiercode 1.1 leaderboard models'),
    ('Code Arena (WebDev)', 'https://benchlm.ai/benchmarks/lmarenawebdev',
     'webdev arena leaderboard elo models'),
]


def log(r):
    print(json.dumps(r, ensure_ascii=False), flush=True)


def чисто(т):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', т or '')).strip()


def взять_таблицу(url):
    """Скачать страницу и достать строки таблицы (список списков ячеек)."""
    r = urllib.request.Request(url, headers={'user-agent': UA, 'accept-language': 'en-US,en;q=0.9'})
    try:
        h = urllib.request.urlopen(r, timeout=45).read().decode('utf-8', 'replace')
    except Exception as e:
        return [], str(e)[:100]
    строки = []
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', h, re.S):
        ячейки = [чисто(c) for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, re.S)]
        ячейки = [c for c in ячейки if c not in ('', '$')]
        if len(ячейки) >= 2 and any(re.search(r'\d', c) for c in ячейки):
            строки.append(ячейки)
    return строки, ''


def наши_строки(строки):
    """Оставить строки, где встречается наша модель."""
    out = []
    for ячейки in строки:
        текст = ' '.join(ячейки)
        if any(н.lower() in текст.lower() for н in НАШИ):
            out.append(ячейки)
    return out


def main():
    мои = [с for i, с in enumerate(СТРАНИЦЫ) if i % ВСЕГО == (SLOT - 1) % ВСЕГО]
    log({'event': 'start', 'slot': SLOT, 'pages': len(мои)})
    итог = []
    запросов = 0
    for имя, url, запрос in мои:
        строки, ошибка = взять_таблицу(url)
        наши = наши_строки(строки)
        head = строки[0] if строки else []
        top = строки[1:6]
        r = искать(запрос)
        запросов += 1
        итог.append({'benchmark': имя, 'url': url, 'query': запрос, 'engine': r['engine'],
                     'header': head, 'top_rows': top, 'our_rows': наши,
                     'rows_total': len(строки), 'search_hits': r['hits'][:4],
                     'error': ошибка})
        log({'event': 'page', 'benchmark': имя, 'rows': len(строки), 'our_rows': len(наши),
             'engine': r['engine'], 'err': ошибка[:40]})
        time.sleep(1.4)
    json.dump({'slot': SLOT, 'queries': запросов, 'pages': итог}, open(ВЫХОД, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    log({'event': 'finish', 'queries': запросов, 'pages': len(итог), 'out': ВЫХОД})


if __name__ == '__main__':
    main()
