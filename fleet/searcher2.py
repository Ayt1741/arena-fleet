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
import sys
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from seek import искать

def log(r):
    print(json.dumps(r, ensure_ascii=False), flush=True)


def найти_файл(имя):
    """Файл запросов ищем и в корне, и в fleet/ — workflow работает из корня репозитория."""
    баз = os.path.basename(имя)
    for путь in (имя, баз, 'fleet/' + баз, os.path.join('..', 'fleet', баз)):
        if os.path.exists(путь):
            return путь
    raise FileNotFoundError(имя)


def main():
    все = []
    with open(найти_файл(ФАЙЛ), encoding='utf-8') as f:
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
