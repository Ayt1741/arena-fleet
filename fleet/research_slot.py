#!/usr/bin/env python3
"""Совет + флот: каждая машина исследует одну тему и присылает результат в бота."""
import json
import os
import re
import sys
import urllib.parse
import urllib.request

SLOT = int(os.environ.get('SLOT', '1'))
TG_TOKEN = os.environ.get('TG_TOKEN', '')
TG_CHAT = os.environ.get('TG_CHAT', '7023156818')

TOPICS = {
 1: ('гибридный поиск BM25 + векторы + RRF', 'hybrid retrieval reciprocal rank fusion bm25 dense'),
 2: ('забывание и важность записей', 'memory decay forgetting agent importance ebbinghaus'),
 3: ('иерархические сводки памяти', 'hierarchical memory summarization agent consolidation'),
 4: ('двувременные факты (когда верно / когда узнали)', 'bitemporal knowledge graph temporal facts agent memory'),
 5: ('поиск противоречий в памяти', 'contradiction detection memory consistency llm agent'),
 6: ('замещение и дедупликация записей', 'memory deduplication supersession versioning agent'),
 7: ('файлы правил и их пределы (AGENTS.md)', 'agents.md instruction file context engineering limits'),
 8: ('принуждение через хуки и проверки', 'agent hook enforcement guardrails compliance verification'),
 9: ('сжатие контекста без потери требований', 'context compaction summarization constraint preservation agent'),
 10: ('оценка памяти на бенчмарках', 'longmemeval benchmark long term memory agent evaluation'),
 11: ('граф знаний как память', 'knowledge graph memory agent entity relations retrieval'),
 12: ('локальные эмбеддинги на CPU', 'static embeddings model2vec sqlite-vec local embedding cpu'),
 13: ('хранение состояния в мессенджере', 'telegram bot api file storage large files chunking backup'),
 14: ('облачные вычисления без сервера', 'github actions self hosted runner free compute parallel jobs'),
 15: ('кэширование префикса промпта', 'prompt caching stable prefix cost latency agent'),
 16: ('параллельные подагенты', 'subagent fan out parallel research orchestration agent'),
 17: ('происхождение факта (откуда узнали)', 'provenance citation tracking agent memory source'),
 18: ('секреты и приватность в памяти', 'secret scanning pii redaction memory pipeline'),
 19: ('переранжирование результатов поиска', 'reranking retrieval cross encoder agent memory'),
 20: ('загрузка памяти на старте сессии', 'session bootstrap context injection agent start memory'),
}


def fetch_arxiv(q, n=5):
    url = ('http://export.arxiv.org/api/query?search_query=' + urllib.parse.quote('all:' + q) +
           '&start=0&max_results=%d&sortBy=relevance' % n)
    try:
        raw = urllib.request.urlopen(url, timeout=60).read().decode('utf-8', 'ignore')
    except Exception as e:
        return [], 'arxiv недоступен: %s' % str(e)[:60]
    items = re.findall(r'<entry>(.*?)</entry>', raw, re.S)
    out = []
    for it in items:
        t = re.search(r'<title>(.*?)</title>', it, re.S)
        s = re.search(r'<summary>(.*?)</summary>', it, re.S)
        if t:
            out.append({'title': re.sub(r'\s+', ' ', t.group(1)).strip(),
                        'summary': re.sub(r'\s+', ' ', (s.group(1) if s else ''))[:600]})
    return out, ''


def ask_llm(prompt, max_tokens=800):
    endpoints = [
        ('https://blockrun.ai/v1/chat/completions', 'nvidia/nemotron-3-ultra-550b'),
        ('https://oai.endpoints.kepler.ai.cloud.ovh.net/v1/chat/completions', 'gpt-oss-120b'),
    ]
    for url, model in endpoints:
        try:
            body = {'model': model, 'max_tokens': max_tokens,
                    'messages': [{'role': 'system',
                                  'content': 'Ты инженер памяти ИИ-агентов. Отвечай по-русски, по пунктам, кратко, только проверяемые меры.'},
                                 {'role': 'user', 'content': prompt}]}
            r = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST')
            r.add_header('content-type', 'application/json')
            d = json.loads(urllib.request.urlopen(r, timeout=180).read().decode())
            txt = (d.get('choices') or [{}])[0].get('message', {}).get('content', '')
            if txt.strip():
                return txt, model
        except Exception:
            continue
    return '', 'нет доступной модели'


def tg_send(text):
    if not TG_TOKEN:
        return False
    for i in range(0, len(text), 3500):
        try:
            r = urllib.request.Request('https://api.telegram.org/bot%s/sendMessage' % TG_TOKEN,
                                       data=json.dumps({'chat_id': TG_CHAT, 'text': text[i:i + 3500]}).encode(),
                                       method='POST')
            r.add_header('Content-Type', 'application/json')
            urllib.request.urlopen(r, timeout=60).read()
        except Exception:
            return False
    return True


def main():
    title, query = TOPICS.get(SLOT, ('тема %d' % SLOT, 'agent memory'))
    print('машина %02d | тема: %s' % (SLOT, title))
    papers, err = fetch_arxiv(query)
    print('  статей найдено:', len(papers), err)
    src = '\n'.join('- %s: %s' % (p['title'], p['summary'][:300]) for p in papers) or '(источники недоступны)'
    prompt = ('Тема: %s.\nНиже — выдержки из научных статей (arXiv).\n%s\n\n'
              'Дай 5 конкретных инженерных мер по этой теме для памяти ИИ-агента: что именно сделать, '
              'как проверить машинно (метрика), и в каком порядке внедрять. Кратко, по пунктам.' % (title, src))
    answer, model = ask_llm(prompt)
    if not answer:
        answer = 'модель недоступна, только источники:\n' + src
    rec = {'slot': SLOT, 'topic': title, 'model': model, 'papers': papers, 'answer': answer}
    with open('research-%02d.json' % SLOT, 'w', encoding='utf-8') as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    head = 'МАШИНА %02d | %s\nмодель: %s | статей: %d\n\n' % (SLOT, title, model, len(papers))
    tg_send(head + answer)
    print('  ответ модели:', len(answer), 'симв. | отправлено в бота:', bool(TG_TOKEN))


if __name__ == '__main__':
    main()
