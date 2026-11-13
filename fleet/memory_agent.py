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
import sys
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from seek import искать

def log(r):
    print(json.dumps(r, ensure_ascii=False), flush=True)


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
