#!/usr/bin/env python3
"""СОВЕТ, КОТОРЫЙ САМ ИЩЕТ В ИНТЕРНЕТЕ (10 руководителей).

Каждый руководитель делает СВОИ поисковые запросы, читает найденные страницы и отвечает
только по найденному, со ссылками. Затем раунд согласования: каждый видит материалы остальных.

  python council_search.py            # 10 руководителей, поиск + ответы + согласование
  python council_search.py 5          # только 5 руководителей
"""
import concurrent.futures
import json
import os
import re
import sys
import urllib.parse
import urllib.request

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/126.0.0.0 Safari/537.36')
OUT = os.environ.get('OUT_DIR', 'state/leaders')

ROLES = [
    ('стратег', ['agent memory architecture best practices 2026',
                 'долговременная память ИИ-агента как устроить']),
    ('инженер', ['sqlite fts5 bm25 hybrid search implementation',
                 'sqlite vector search sqlite-vec production']),
    ('критик', ['agent memory failure modes forgetting wrong recall',
                'почему ИИ-агент забывает требования заказчика']),
    ('исследователь', ['arxiv long-term memory LLM agent 2026',
                       'MemGPT Letta Mem0 Zep сравнение памяти']),
    ('практик', ['deploy agent memory production sqlite python stdlib',
                 'backup restore state agent memory telegram bot']),
    ('архитектор', ['context engineering layered memory rules skills hooks',
                    'instruction file AGENTS.md enforcement limits']),
    ('скептик', ['memory poisoning prompt injection agent defense',
                 'риски хранения памяти агента утечка персональных данных']),
    ('аналитик', ['memory retrieval evaluation recall mrr benchmark',
                  'как измерить качество памяти агента метрики']),
    ('методист', ['runbook memory bootstrap restore session start',
                  'регламент ведения памяти агента документ']),
    ('проверяющий', ['compliance verification hooks CI guardrails agent',
                     'как принудить агента соблюдать правила проверка']),
]


def search(q, n=6):
    """Поиск без ключей: html.duckduckgo.com (POST). Возвращает заголовок, ссылку, сниппет."""
    try:
        data = urllib.parse.urlencode({'q': q, 'kl': 'ru-ru'}).encode()
        r = urllib.request.Request('https://html.duckduckgo.com/html/', data=data, method='POST')
        r.add_header('User-Agent', UA)
        r.add_header('Accept-Language', 'ru-RU,ru;q=0.9,en;q=0.8')
        with urllib.request.urlopen(r, timeout=40) as x:
            html = x.read().decode('utf-8', 'ignore')
    except Exception as e:
        return [], 'поиск не ответил: %s' % str(e)[:60]
    items = re.findall(r'<div class="result results_links.*?</div>\s*</div>', html, re.S)[:n]
    out = []
    for block in items:
        m = re.search(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        s = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', block, re.S)
        if not m:
            continue
        url = urllib.parse.unquote(m.group(1))
        url = re.sub(r'^//duckduckgo\.com/l/\?uddg=', '', url)
        title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        snip = re.sub(r'<[^>]+>', '', s.group(1)).strip() if s else ''
        out.append({'title': title, 'url': url, 'snippet': snip[:400]})
    return out, ''



def search_arxiv(q, n=3):
    try:
        url = ('http://export.arxiv.org/api/query?search_query=' + urllib.parse.quote('all:' + q) +
               '&start=0&max_results=%d&sortBy=relevance' % n)
        raw = urllib.request.urlopen(url, timeout=40).read().decode('utf-8', 'ignore')
    except Exception:
        return []
    out = []
    for it in re.findall(r'<entry>(.*?)</entry>', raw, re.S)[:n]:
        t = re.search(r'<title>(.*?)</title>', it, re.S)
        i = re.search(r'<id>(.*?)</id>', it, re.S)
        sm = re.search(r'<summary>(.*?)</summary>', it, re.S)
        if t and i:
            out.append({'title': re.sub(r'\s+', ' ', t.group(1)).strip(), 'url': i.group(1).strip(),
                        'snippet': re.sub(r'\s+', ' ', (sm.group(1) if sm else ''))[:400]})
    return out


def search_wiki(q, n=3):
    try:
        url = ('https://ru.wikipedia.org/w/api.php?action=query&list=search&format=json&srlimit=%d&srsearch=' % n +
               urllib.parse.quote(q))
        d = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={'user-agent': UA}),
                                              timeout=40).read().decode())
    except Exception:
        return []
    return [{'title': h['title'], 'url': 'https://ru.wikipedia.org/wiki/' + urllib.parse.quote(h['title'].replace(' ', '_')),
             'snippet': re.sub(r'<[^>]+>', '', h.get('snippet', ''))[:400]} for h in d.get('query', {}).get('search', [])]


def search_github(q, n=3):
    try:
        url = ('https://api.github.com/search/repositories?q=' +
               urllib.parse.quote(' '.join(re.findall(r'[A-Za-z]{3,}', q)[:3]) + ' in:name,description,readme') +
               '&sort=stars&per_page=%d' % n)
        d = json.loads(urllib.request.urlopen(urllib.request.Request(
            url, headers={'accept': 'application/vnd.github+json', 'user-agent': UA}), timeout=40).read().decode())
    except Exception:
        return []
    return [{'title': '%s (%d★)' % (i['full_name'], i['stargazers_count']), 'url': i['html_url'],
             'snippet': (i.get('description') or '')[:400]} for i in d.get('items', [])[:n]]


def relevant(items, q):
    """Оставляем только то, где встречается слово запроса — иначе в источники лезет мусор."""
    words = [w.lower() for w in re.findall(r'[A-Za-zА-Яа-я]{4,}', q)]
    out = []
    for it in items:
        blob = (it['title'] + ' ' + it.get('snippet', '') + ' ' + it['url']).lower()
        if any(w in blob for w in words):
            out.append(it)
    return out


def search_any(q, n=6):
    """Обычный поиск с тремя попытками (лимит проходит за паузу), затем запасные источники."""
    import time as _t
    last = ''
    for attempt in range(3):
        items, err = search(q, n)
        items = relevant(items, q)
        if items:
            return items, ''
        last = err or 'пусто'
        _t.sleep(15 + attempt * 10)
    extra = search_arxiv(q, 4)
    if len(extra) < 2:
        extra += search_wiki(q, 2)
    if len(extra) < 2:
        extra += search_github(q, 3)
    extra = relevant(extra, q) or extra
    return extra, ('основной поиск промолчал (%s), взял запасные источники: %d' % (last, len(extra)))


def fetch(url, limit=2500):
    """Читает страницу и вытаскивает текст (без тегов)."""
    try:
        r = urllib.request.Request(url, headers={'user-agent': UA, 'accept-language': 'ru,en'})
        with urllib.request.urlopen(r, timeout=30) as x:
            raw = x.read(400000).decode('utf-8', 'ignore')
    except Exception as e:
        return ''
    raw = re.sub(r'(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>', ' ', raw)
    txt = re.sub(r'(?s)<[^>]+>', ' ', raw)
    txt = re.sub(r'\s+', ' ', txt).strip()
    return txt[:limit]


def ask_model(prompt, max_tokens=900):
    for url, model in [('https://blockrun.ai/v1/chat/completions', 'nvidia/nemotron-3-ultra-550b'),
                       ('https://oai.endpoints.kepler.ai.cloud.ovh.net/v1/chat/completions', 'gpt-oss-120b')]:
        try:
            body = {'model': model, 'max_tokens': max_tokens,
                    'messages': [{'role': 'system', 'content':
                                  'Ты член совета инженеров памяти ИИ-агентов. Пиши ТОЛЬКО ПО-РУССКИ, '
                                  'без рассуждений и без пересказа задачи. Сразу 5 мер списком. '
                                  'У каждой меры: действие, машинная проверка (метрика), ссылка [N] из присланного списка. '
                                  'Если источник к мере не подходит — не выдумывай ссылку, пиши [нет источника].'},
                                 {'role': 'user', 'content': prompt}]}
            r = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST')
            r.add_header('content-type', 'application/json')
            d = json.loads(urllib.request.urlopen(r, timeout=180).read().decode())
            t = (d.get('choices') or [{}])[0].get('message', {}).get('content', '')
            if t.strip():
                return t.strip(), model
        except Exception:
            continue
    return '', 'нет модели'


def leader(i):
    role, queries = ROLES[i]
    found, errors, pages = [], [], {}
    for q in queries:
        items, err = search_any(q)
        import time as _t
        _t.sleep(3)
        if err:
            errors.append(err)
        found += items
    # читаем до 4 страниц
    for it in found[:4]:
        txt = fetch(it['url'])
        if txt:
            pages[it['url']] = txt
    srcs = []
    for k, it in enumerate(found[:8], 1):
        srcs.append({'n': k, 'title': it['title'], 'url': it['url'],
                     'snippet': it['snippet'], 'read': pages.get(it['url'], '')[:900]})
    listing = '\n'.join('[%d] %s — %s\n    %s' % (s['n'], s['title'][:90], s['url'],
                                                  (s['read'] or s['snippet'])[:500]) for s in srcs)
    prompt = ('Ты — %s в совете из 10 руководителей. Задача: как держать в памяти ИИ-агента все законы '
              'заказчика и проверенные факты так, чтобы они поднимались сами в каждой сессии, не терялись '
              'и не противоречили друг другу.\n\nНайденные источники:\n%s\n\n'
              'Дай 5 мер. У каждой: что сделать, как проверить машинно (метрика), ссылка [N] из списка. '
              'В конце — порядок внедрения 1→5.' % (role, listing or '(источники не найдены)'))
    answer, model = ask_model(prompt)
    text = ('# Руководитель L%02d — %s\n\nмодель: %s | поисковых запросов: %d | источников: %d | страниц прочитано: %d\n\n'
            '%s\n\n## Источники (найдено поиском)\n%s\n' %
            (i + 1, role, model, len(queries), len(srcs), len(pages), answer or '(модель не ответила)',
             '\n'.join('- [%d] %s — %s' % (s['n'], s['title'][:100], s['url']) for s in srcs)))
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, 'L%02d.md' % (i + 1)), 'w', encoding='utf-8').write(text)
    return i, role, model, len(srcs), len(pages), len(answer), [s['url'] for s in srcs], errors


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 10
    print('руководителей в работе: %d (каждый ищет в интернете сам)' % n)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        for r in ex.map(leader, range(n)):
            results.append(r)
            print('L%02d %-12s модель %-28s источников %2d | прочитано страниц %d | ответ %4d симв.' %
                  ((r[0] + 1), r[1], r[2][:28], r[3], r[4], r[5]))
            if r[7]:
                print('   замечание:', r[7][0])
    # согласование: раунд 2
    mats = {}
    for i in range(n):
        p = os.path.join(OUT, 'L%02d.md' % (i + 1))
        mats[i] = open(p, encoding='utf-8').read() if os.path.exists(p) else ''
    for i in range(n):
        others = '\n\n'.join(mats[j][:700] for j in range(n) if j != i)
        prompt = ('Материал твоего коллеги-советника:\n%s\n\nТвои источники: %s\n\n'
                  'Согласование ПО-РУССКИ: что принимаешь (3 пункта), что отклоняешь и почему (2 пункта), '
                  'что добавляешь от себя. Указывай, из какого источника это взято [N].' %
                  (others[:3000], ', '.join(results[i][6][:6])))
        text, model = ask_model(prompt, 600)
        if text:
            with open(os.path.join(OUT, 'L%02d-r2.md' % (i + 1)), 'a', encoding='utf-8') as f:
                f.write('\n\n## Согласование (раунд 2)\n\nмодель: %s\n\n%s\n' % (model, text))
    print('согласование записано для %d руководителей' % n)
    json.dump([{'role': r[1], 'model': r[2], 'sources': r[3], 'read': r[4], 'chars': r[5],
                'urls': r[6]} for r in results], open('совет-итог.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
