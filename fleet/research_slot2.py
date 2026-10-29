#!/usr/bin/env python3
"""Совет + флот, раунд 2: память агента. Машина = одна тема.
Источники: arXiv API + поиск репозиториев GitHub (реальный код) -> модель -> Telegram.
"""
import json, os, re, urllib.parse, urllib.request

SLOT = int(os.environ.get('SLOT', '1'))
TG_TOKEN = os.environ.get('TG_TOKEN', '')
TG_CHAT = os.environ.get('TG_CHAT', '7023156818')

TOPICS = {
 1: ('память как операционная система агента', 'agent memory operating system survey LLM'),
 2: ('саморедактируемая память (MemGPT/Letta)', 'self editing memory LLM agent MemGPT Letta'),
 3: ('сон и консолидация памяти между сессиями', 'sleep time compute memory consolidation LLM agent'),
 4: ('процедурная память: навыки, а не факты', 'procedural memory skills agent learning reuse'),
 5: ('защита от отравления памяти', 'memory poisoning attack defense LLM agent'),
 6: ('промпт-инъекция через сохранённую память', 'prompt injection persistent memory agent defense'),
 7: ('сжатие векторов без потери качества', 'vector quantization compression RaBitQ binary embedding memory'),
 8: ('журнал событий как память (append-only)', 'event sourcing append only log agent state recovery'),
 9: ('бесконфликтная синхронизация памяти (CRDT)', 'CRDT conflict free replicated data type sync state'),
 10: ('бенчмарки долгой памяти 2026', 'LoCoMo LongMemEval benchmark long term memory evaluation 2026'),
 11: ('семантический кэш ответов', 'semantic caching llm responses cost latency'),
 12: ('нарезка текста на куски для поиска', 'chunking strategy retrieval augmented generation evaluation'),
 13: ('извлечение правил из длинных диалогов', 'distill rules from conversation into instructions agent'),
 14: ('память нескольких агентов (общая и личная)', 'multi agent shared memory blackboard collaboration'),
 15: ('память на SQLite и FTS5 в продакшене', 'sqlite fts5 full text search production scale'),
 16: ('переранжирование без больших моделей', 'lightweight reranking cross encoder small model retrieval'),
 17: ('оценка памяти без человека (LLM-судья)', 'LLM as judge evaluation memory recall faithfulness'),
 18: ('сжатие контекста с сохранением требований', 'context compression constraint preservation long conversation'),
 19: ('скрытые ошибки памяти: ложные воспоминания', 'false memory hallucination retrieval agent failure analysis'),
 20: ('перенос памяти между разными моделями', 'portable memory format across models interoperability agent'),
}


def arxiv(q, n=4):
    url = ('http://export.arxiv.org/api/query?search_query=' + urllib.parse.quote('all:' + q) +
           '&start=0&max_results=%d&sortBy=relevance' % n)
    try:
        raw = urllib.request.urlopen(url, timeout=60).read().decode('utf-8', 'ignore')
    except Exception as e:
        return [], 'arxiv: %s' % str(e)[:50]
    out = []
    for it in re.findall(r'<entry>(.*?)</entry>', raw, re.S):
        t = re.search(r'<title>(.*?)</title>', it, re.S)
        s = re.search(r'<summary>(.*?)</summary>', it, re.S)
        if t:
            out.append({'title': re.sub(r'\s+', ' ', t.group(1)).strip(),
                        'summary': re.sub(r'\s+', ' ', (s.group(1) if s else ''))[:400]})
    return out, ''


def gh(q, n=4):
    """Реальный код: репозитории GitHub по теме. Запрос укорачиваем — длинный даёт 0."""
    words = [w for w in re.findall(r'[A-Za-z]{3,}', q)]
    for k in (3, 2, 1):
        if len(words) < k:
            continue
        query = ' '.join(words[:k]) + ' in:name,description,readme'
        url = 'https://api.github.com/search/repositories?q=' + urllib.parse.quote(query) + '&sort=stars&per_page=%d' % n
        r = urllib.request.Request(url, headers={'accept': 'application/vnd.github+json', 'user-agent': 'flot'})
        try:
            d = json.loads(urllib.request.urlopen(r, timeout=60).read().decode())
        except Exception as e:
            return [], 'github: %s' % str(e)[:50]
        if d.get('items'):
            return [{'title': '%s (%d★)' % (i['full_name'], i['stargazers_count']),
                     'summary': (i.get('description') or '')[:200]} for i in d['items']], ''
    return [], ''


def ask(prompt, max_tokens=900):
    for url, model in [('https://blockrun.ai/v1/chat/completions', 'nvidia/nemotron-3-ultra-550b'),
                       ('https://oai.endpoints.kepler.ai.cloud.ovh.net/v1/chat/completions', 'gpt-oss-120b')]:
        try:
            body = {'model': model, 'max_tokens': max_tokens,
                    'messages': [{'role': 'system', 'content': 'Ты инженер памяти ИИ-агентов. По-русски, по пунктам, только проверяемые меры с метрикой.'},
                                 {'role': 'user', 'content': prompt}]}
            r = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST')
            r.add_header('content-type', 'application/json')
            d = json.loads(urllib.request.urlopen(r, timeout=180).read().decode())
            t = (d.get('choices') or [{}])[0].get('message', {}).get('content', '')
            if t.strip():
                return t, model
        except Exception:
            continue
    return '', 'нет модели'


def tg(text):
    if not TG_TOKEN:
        return False
    try:
        r = urllib.request.Request('https://api.telegram.org/bot%s/sendMessage' % TG_TOKEN,
                                   data=json.dumps({'chat_id': TG_CHAT, 'text': text[:3800]}).encode(), method='POST')
        r.add_header('Content-Type', 'application/json')
        urllib.request.urlopen(r, timeout=60).read()
        return True
    except Exception:
        return False


def main():
    title, q = TOPICS.get(SLOT, ('тема', 'agent memory'))
    papers, e1 = arxiv(q)
    repos, e2 = gh(q)
    src = '\n'.join(['- [статья] %s: %s' % (p['title'], p['summary'][:220]) for p in papers] +
                    ['- [код] %s: %s' % (p['title'], p['summary']) for p in repos])
    prompt = ('Тема: %s.\nНайденное в интернете:\n%s\n\n'
              'Дай 5 мер для памяти ИИ-агента: что сделать, как проверить машинно, в каком порядке. '
              'Если по теме есть готовый рабочий репозиторий — назови его и что именно оттуда взять.' % (title, src))
    ans, model = ask(prompt)
    rec = {'slot': SLOT, 'topic': title, 'model': model, 'papers': papers, 'repos': repos, 'answer': ans}
    json.dump(rec, open('research2-%02d.json' % SLOT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('машина %02d | %s | статей %d | репозиториев %d | ответ %d симв. | %s' %
          (SLOT, title, len(papers), len(repos), len(ans), 'в бота' if tg('#%02d %s\n\n%s' % (SLOT, title, ans)) else 'без бота'))


if __name__ == '__main__':
    main()
