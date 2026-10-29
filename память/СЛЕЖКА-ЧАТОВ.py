#!/usr/bin/env python3
"""СЛЕЖКА ЗА ПЕРЕПИСКОЙ — каждая пара «запрос → ответ» из каждого чата сама уезжает в бота.

Работает по кругу (или один раз с --once):
 1. вход по почте/паролю из АККАУНТЫ.json (браузер не нужен) либо cookie из сессии браузера;
 2. читает список чатов: /api/history/unified (все страницы);
 3. для каждого НОВОГО чата читает все сообщения: /api/chat/<id>/messages;
 4. каждое сообщение → в память (источник = chat:<аккаунт>:<чат>), в файл журнала и в бота;
 5. состояние (какие чаты уже сохранены) в файле, чтобы не дублировать.

Запуск:
  python СЛЕЖКА-ЧАТОВ.py --once      # один проход по всем аккаунтам
  python СЛЕЖКА-ЧАТОВ.py             # по кругу, пауза 300 с
  python СЛЕЖКА-ЧАТОВ.py --mock      # самопроверка на выдуманном сервере (доказывает, что сохраняет)
"""
import base64
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, 'слежка-состояние.json')
JOURNAL = os.path.join(HERE, 'переписка.jsonl')
SESSIONS = os.path.join(HERE, 'сессии.json')
ACCOUNTS = os.path.join(HERE, 'АККАУНТЫ.json')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/126.0.0.0 Safari/537.36')
BASE = os.environ.get('ARENA_BASE', 'https://arena.ai')


def tg():
    try:
        c = json.load(open(os.path.join(HERE, '..', 'tg', 'config.json'), encoding='utf-8'))
        return c['token'], str(c['chat_id'])
    except Exception:
        return '', ''


def tg_msg(text):
    tok, chat = tg()
    if not tok:
        return False
    try:
        r = urllib.request.Request('https://api.telegram.org/bot%s/sendMessage' % tok,
                                   data=json.dumps({'chat_id': chat, 'text': text[:3800],
                                                    'disable_web_page_preview': True}).encode(), method='POST')
        r.add_header('Content-Type', 'application/json')
        urllib.request.urlopen(r, timeout=60).read()
        return True
    except Exception:
        return False


def tg_doc(path, caption):
    tok, chat = tg()
    if not tok:
        return False
    boundary = '----j%d' % int(time.time() * 1000)
    body = ('--%s\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n%s\r\n'
            '--%s\r\nContent-Disposition: form-data; name="caption"\r\n\r\n%s\r\n'
            '--%s\r\nContent-Disposition: form-data; name="document"; filename="%s"\r\n'
            'Content-Type: application/octet-stream\r\n\r\n'
            % (boundary, chat, boundary, caption, boundary, os.path.basename(path))).encode() + \
        open(path, 'rb').read() + ('\r\n--%s--\r\n' % boundary).encode()
    r = urllib.request.Request('https://api.telegram.org/bot%s/sendDocument' % tok, data=body, method='POST')
    r.add_header('Content-Type', 'multipart/form-data; boundary=%s' % boundary)
    try:
        return json.loads(urllib.request.urlopen(r, timeout=600).read().decode()).get('ok', False)
    except Exception:
        return False


def sign_in(email, password):
    """Вход без браузера: отдаёт строку cookie для запросов."""
    r = urllib.request.Request(BASE + '/nextjs-api/sign-in/email',
                               data=json.dumps({'email': email, 'password': password}).encode(), method='POST')
    for k, v in {'content-type': 'application/json', 'user-agent': UA,
                 'origin': BASE, 'referer': BASE + '/text'}.items():
        r.add_header(k, v)
    with urllib.request.urlopen(r, timeout=45) as x:
        pairs = []
        for c in x.headers.get_all('Set-Cookie') or []:
            n, rest = c.split('=', 1)
            pairs.append('%s=%s' % (n, rest.split(';')[0]))
        x.read()
    return '; '.join(pairs)


def get(cookie, path):
    r = urllib.request.Request(BASE + path, headers={'cookie': cookie, 'user-agent': UA,
                                                     'accept': 'application/json'})
    with urllib.request.urlopen(r, timeout=60) as x:
        return json.loads(x.read().decode())


def save_to_memory(text, source):
    try:
        import importlib
        sys.path.insert(0, HERE)
        mem = importlib.import_module('MEMORY')
        return mem.add(text, source)
    except Exception as e:
        return 'в память не легло: %s' % str(e)[:60]


def collect(cookie, account, state):
    """Один аккаунт: все чаты, все сообщения, только новое."""
    added_chats = added_msgs = 0
    cursor, entries = None, []
    for _ in range(80):
        q = '/api/history/unified?limit=20&includeArchived=true&archivedOnly=false' + \
            (('&cursor=' + urllib.parse.quote(cursor)) if cursor else '')
        d = get(cookie, q)
        entries += d.get('entries', [])
        p = d.get('pagination') or {}
        if not p.get('hasMore') or not p.get('cursor'):
            break
        cursor = p['cursor']
    for e in entries:
        cid = e.get('id')
        if not cid:
            continue
        key = '%s:%s' % (account, cid)
        if key in state['chats']:
            continue
        msgs, cur = [], None
        for _ in range(40):
            q = '/api/chat/%s/messages?limit=50' % cid + (('&cursor=' + urllib.parse.quote(cur)) if cur else '')
            d = get(cookie, q)
            msgs += d.get('data') or d.get('messages') or []
            cur = (d.get('pagination') or {}).get('cursor') or d.get('nextCursor')
            if not cur:
                break
        text_parts = []
        for m in msgs:
            role = m.get('role') or '?'
            c = m.get('content') or m.get('text') or ''
            if isinstance(c, list):
                c = ' '.join(str(x.get('text', '')) if isinstance(x, dict) else str(x) for x in c)
            text_parts.append({'role': role, 'text': c})
        rec = {'account': account, 'chat': cid, 'title': (e.get('title') or '')[:120],
               'mode': e.get('mode') or e.get('type'), 'link': '%s/c/%s' % (BASE, cid),
               'saved': time.strftime('%Y-%m-%d %H:%M:%S'), 'messages': text_parts}
        with open(JOURNAL, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        qa = ['[%s] %s → %s' % (rec['title'] or cid, p['role'], p['text'][:600]) for p in text_parts if p['text']]
        save_to_memory('ПЕРЕПИСКА %s | чат %s | %s\n%s' % (account, cid, rec['link'], '\n\n'.join(qa))[:6000],
                       'chat:%s:%s' % (account, cid))
        state['chats'][key] = {'saved': rec['saved'], 'messages': len(msgs), 'title': rec['title']}
        added_chats += 1
        added_msgs += len(msgs)
        print('   чат %s «%s»: сообщений %d' % (cid[:10], rec['title'][:40], len(msgs)))
    return added_chats, added_msgs, len(entries)


def accounts():
    """Список: (название, cookie). Сначала живые cookie из сессии браузера, потом вход по паролю."""
    out = []
    if os.path.exists(SESSIONS):
        try:
            d = json.load(open(SESSIONS, encoding='utf-8'))
            for p in d.get('profiles', []):
                arena = [c for c in p['cookies'] if 'arena.ai' in (c.get('domain') or '')]
                if any(c['name'].startswith('arena-auth-prod-v1') for c in arena):
                    out.append(('профиль "%s"' % p['label'], '; '.join('%s=%s' % (c['name'], c['value']) for c in arena)))
        except Exception:
            pass
    if os.path.exists(ACCOUNTS):
        for a in json.load(open(ACCOUNTS, encoding='utf-8')):
            out.append((a['email'], None, a['pass']))
    return out


def run_once():
    state = json.load(open(STATE, encoding='utf-8')) if os.path.exists(STATE) else {'chats': {}}
    total_chats = total_msgs = 0
    for item in accounts():
        if len(item) == 3:
            name, _, pw = item
            try:
                cookie = sign_in(name, pw)
            except Exception as e:
                print('  %-34s вход не прошёл: %s' % (name, str(e)[:60]))
                continue
        else:
            name, cookie = item
        try:
            ch, ms, seen = collect(cookie, name, state)
            total_chats += ch
            total_msgs += ms
            print('  %-34s чатов на сервере: %d, новых сохранено: %d, сообщений: %d' % (name, seen, ch, ms))
        except Exception as e:
            print('  %-34s ошибка чтения: %s' % (name, str(e)[:80]))
    json.dump(state, open(STATE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    try:
        import importlib
        sys.path.insert(0, HERE)
        print('  в бота новые записи памяти:', importlib.import_module('MEMORY').autosync())
    except Exception as e:
        print('  отправка в бота не удалась:', str(e)[:70])
    line = 'СЛЕЖКА: новых чатов %d, сообщений %d, всего в памяти чатов %d | %s' % (
        total_chats, total_msgs, len(state['chats']), time.strftime('%d.%m %H:%M'))
    print(line)
    tg_msg(line)
    if os.path.exists(JOURNAL) and os.path.getsize(JOURNAL) > 0:
        tg_doc(JOURNAL, 'переписка целиком: %d КБ' % (os.path.getsize(JOURNAL) // 1024))
    return total_chats


def mock():
    """Самопроверка: поднимает выдуманный сервер Арены и прогоняет полный цикл сохранения."""
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Set-Cookie', 'arena-auth-prod-v1.0=base64-TEST; Path=/')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            ln = int(self.headers.get('Content-Length') or 0)
            if ln:
                self.rfile.read(ln)
            self._send({'ok': True, 'user': {'email': 'test@mail.ru'}})

        def do_GET(self):
            if 'history/unified' in self.path:
                self._send({'entries': [{'id': 'chat-1', 'title': 'Проверка памяти', 'mode': 'direct'}],
                            'pagination': {'hasMore': False}})
            elif 'messages' in self.path:
                self._send({'data': [{'role': 'user', 'content': 'запрос заказчика'},
                                     {'role': 'assistant', 'content': 'ответ модели'}]})
            else:
                self._send({})

    srv = http.server.HTTPServer(('127.0.0.1', 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    global BASE
    BASE = 'http://127.0.0.1:%d' % port
    if os.path.exists(STATE):
        os.remove(STATE)
    print('выдуманный сервер на', BASE)
    n = run_once()
    state = json.load(open(STATE, encoding='utf-8'))
    saved = state['chats']
    ok = n >= 1 and any(v['messages'] == 2 for v in saved.values())
    print('САМОПРОВЕРКА: чатов сохранено %d, сообщений в записи: %s → %s' %
          (len(saved), [v['messages'] for v in saved.values()], 'ПРОЙДЕНА' if ok else 'ПРОВАЛЕНА'))
    srv.shutdown()
    return 0 if ok else 1


if __name__ == '__main__':
    if '--mock' in sys.argv:
        sys.exit(mock())
    if '--once' in sys.argv:
        sys.exit(0 if run_once() >= 0 else 1)
    while True:
        try:
            run_once()
        except Exception as e:
            print('сбой прохода:', str(e)[:100])
        time.sleep(int(os.environ.get('PAUSE', '300')))
