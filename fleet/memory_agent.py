#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""АГЕНТ «ПАМЯТЬ» — 30 машин ищут, как сделать память агента лучше (требование хода 53).

Каждая машина берёт свои темы и по каждой делает реальные запросы к поисковику
( bing → ddg-lite → marginalia → ddg-html; DuckDuckGo отдаёт заглушку, поэтому
он в запасном порядке) и собирает найденное с цитатами и ссылками.

Артефакт: memory-<slot>.json
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

SLOT = int(os.environ.get('SLOT', '1'))
ВСЕГО = int(os.environ.get('SLOTS', '30'))
ВЫХОД = os.environ.get('OUT', 'memory-%02d.json' % SLOT)
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/126.0.0.0 Safari/537.36')

ТЕМЫ = [
    ('гибридный поиск BM25 + векторы + RRF', ['hybrid retrieval bm25 dense reciprocal rank fusion',
                                                'hybrid search rrf implementation production']),
    ('забывание и важность записей', ['memory decay forgetting curve agent memory importance',
                                      'agent memory decay function implementation']),
    ('иерархические сводки памяти', ['hierarchical memory summarization consolidation agent',
                                     'memory consolidation summarization levels']),
    ('двувременные факты', ['bitemporal knowledge graph temporal facts agent memory',
                            'valid time transaction time knowledge graph']),
    ('поиск противоречий', ['contradiction detection memory consistency llm agent',
                             'detecting contradictions in long term memory']),
    ('дедупликация и версии', ['memory deduplication supersession versioning agent',
                                'semantic dedup vector database near duplicate detection']),
    ('файлы правил и их пределы', ['agents.md instruction file context engineering limits',
                                   'instruction file hierarchy agent context limits']),
    ('принуждение через хуки и проверки', ['agent hook enforcement guardrails compliance check',
                                           'llm output verification gate tool']),
    ('сжатие контекста без потери требований', ['context compaction summarization preserve constraints agent',
                                                 'context compression llm keep requirements']),
    ('оценка памяти на бенчмарках', ['longmemeval benchmark long term memory agent',
                                     'locomo benchmark memory evaluation']),
    ('граф знаний как память', ['knowledge graph agent memory entity retrieval',
                                 'neo4j agent memory graph rag']),
    ('эмбеддинги на CPU', ['static embeddings model2vec sqlite-vec cpu embedding',
                           'fastembed local embedding cpu performance']),
    ('хранение состояния в мессенджере', ['telegram bot api sendDocument 50mb limit chunking',
                                          'telegram bot api getFile 20mb limit']),
    ('облачные вычисления без сервера', ['github actions matrix parallel free runners public repo',
                                         'github actions concurrency limits free plan']),
    ('кэширование префикса промпта', ['prompt caching stable prefix cost latency',
                                      'anthropic prompt cache breakpoint tool use']),
    ('параллельные подагенты', ['subagent fan out parallel research orchestration agent',
                                'multi agent research parallel tool calls']),
    ('происхождение факта', ['provenance citation tracking agent memory source',
                              'citation grounding agent memory source tracking']),
    ('секреты и приватность в памяти', ['secret scanning pii redaction memory pipeline',
                                         'gitleaks secret scanning github action']),
    ('переранжирование результатов', ['reranking retrieval cross encoder agent memory',
                                      'reranker cross encoder latency recall tradeoff']),
    ('загрузка памяти на старте', ['session bootstrap context injection agent start memory',
                                   'memory injection prompt startup context']),
    ('память в формате ядра и ссылок', ['compactly structured agent instructions index',
                                         'keep instructions index under 150 lines context']),
    ('защита от подмены журнала', ['append only log tamper evident hash chain',
                                    'merkle tree append only audit log verification']),
    ('сжатие журнала в ядро', ['log compaction summarization retain rules',
                                'progressive disclosure context memory compaction']),
    ('поиск по журналу за секунды', ['bm25 sqlite fts5 unicode61 tokenizer russian',
                                     'sqlite fts5 porter tokenizer prefix search speed']),
    ('замер качества памяти', ['recall at 5 ndcg mrr retrieval evaluation',
                               'retrieval evaluation metrics recall ndcg mrr python']),
    ('агентная память в 2026', ['agent memory 2026 state of the art long context',
                                'long context vs memory agent benchmark 2026']),
    ('хранение в GitHub как память', ['github repository as durable agent memory storage',
                                      'git based memory store agent']),
    ('телеграм как долговременное хранилище', ['telegram channel storage backup files bot',
                                                'telegram bot upload large archive file limit']),
    ('бесплатные API для агентов', ['free llm api tier no credit card 2026',
                                     'free openai compatible api endpoint free tier limits']),
    ('проверка фактов агентом', ['agent fact verification citation check pipeline',
                                 'self check factual claim verification llm']),
]

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
    мои = [т for i, т in enumerate(ТЕМЫ) if i % ВСЕГО == (SLOT - 1) % ВСЕГО]
    log({'event': 'start', 'slot': SLOT, 'topics': len(мои)})
    итог = []
    n = 0
    for тема, вопросы in мои:
        блок = {'topic': тема, 'queries': []}
        for q in вопросы:
            r = искать(q)
            n += 1
            блок['queries'].append({'q': q, 'engine': r['engine'], 'hits': r['hits'][:4]})
            log({'event': 'query', 'n': n, 'topic': тема[:40], 'q': q[:60],
                 'engine': r['engine'], 'hits': len(r['hits'])})
            time.sleep(1.3)
        итог.append(блок)
    json.dump({'slot': SLOT, 'queries': n, 'topics': итог}, open(ВЫХОД, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    log({'event': 'finish', 'queries': n, 'out': ВЫХОД})


if __name__ == '__main__':
    main()
