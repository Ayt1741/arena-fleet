#!/usr/bin/env python3
"""Одна машина = один аккаунт = один IP. Вход, проверка, отчёт в Telegram."""
import base64
import io
import json
import os
import re
import sqlite3
import urllib.parse
import urllib.request
import zipfile

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
SLOT = int(os.environ.get('SLOT', '0'))
PAIR = os.environ.get('A%02d' % SLOT, '') or ''
TG_TOKEN = os.environ.get('TG_TOKEN', '')
MEMORY_PARTS = os.environ.get('MEMORY_PARTS', '')
TASK = os.environ.get('TASK', 'что уже сделано по проекту')
TG_CHAT = os.environ.get('TG_CHAT', '7023156818')


def post_json(url, body, headers):
    r = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST')
    r.add_header('content-type', 'application/json')
    for k, v in headers.items():
        r.add_header(k, v)
    with urllib.request.urlopen(r, timeout=60) as x:
        return x.status, x.read().decode(), (x.headers.get_all('set-cookie') or [])


def get_json(url, headers):
    r = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(r, timeout=60) as x:
        return x.status, x.read().decode()


def tg(text):
    if not TG_TOKEN:
        return
    try:
        post_json('https://api.telegram.org/bot%s/sendMessage' % TG_TOKEN,
                  {'chat_id': TG_CHAT, 'text': text}, {})
    except Exception as e:
        print('tg:', e)


def token_from(cookies):
    parts = {}
    for c in cookies:
        kv = c.split(';')[0]
        if '=' not in kv:
            continue
        k, v = kv.split('=', 1)
        m = re.match(r'arena-auth-prod-v1(?:\.(\d+))?$', k)
        if m:
            parts[int(m.group(1) or 0)] = urllib.parse.unquote(v)
    blob = ''.join(parts[k] for k in sorted(parts))
    if blob.startswith('base64-'):
        blob = blob[7:]
    try:
        raw = base64.b64decode(blob + '=' * (-len(blob) % 4), validate=False).decode('utf-8', 'ignore')
    except Exception:
        return ''
    t = re.search(r'access_token\\?"\s*:\s*\\?"(eyJ[A-Za-z0-9_\-\.]+)', raw)
    return t.group(1) if t else ''


def memory_ping(text):
    """Спросить общую память: скачать базу из бота частями и найти по теме."""
    parts = [x for x in os.environ.get('MEMORY_PARTS', '').split(',') if x.strip()]
    if not (TG_TOKEN and parts):
        return 'память: не подключена'
    try:
        buf = b''
        for fid in parts:
            info = json.loads(urllib.request.urlopen(
                'https://api.telegram.org/bot%s/getFile?file_id=%s' % (TG_TOKEN, fid.strip()), timeout=180).read().decode())
            path = info['result']['file_path']
            buf += urllib.request.urlopen('https://api.telegram.org/file/bot%s/%s' % (TG_TOKEN, path), timeout=600).read()
        os.makedirs('/tmp/memdb', exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(buf)) as zf:
            zf.extract('memory.db', path='/tmp/memdb')
        c = sqlite3.connect('/tmp/memdb/memory.db')
        total, = c.execute('SELECT count(*) FROM fts').fetchone()
        words = re.findall(r'[\wа-яё]{3,}', text.lower())[:8]
        hits = []
        if words:
            q = ' OR '.join('"%s"' % w for w in words)
            try:
                hits = c.execute('SELECT title FROM fts WHERE fts MATCH ? ORDER BY bm25(fts) LIMIT 3', (q,)).fetchall()
            except Exception:
                pass
        c.close()
        top = '; '.join(h[0][:55] for h in hits) or 'ничего не нашлось'
        return 'память: %d записей | по теме: %s' % (total, top)
    except Exception as e:
        return 'память: сбой (%s)' % str(e)[:70]


def main():
    ip = ''
    for url in ('https://api.ipify.org', 'https://ifconfig.me/ip'):
        try:
            ip = get_json(url, {'user-agent': UA})[1].strip()
            if ip:
                break
        except Exception:
            pass
    if not PAIR:
        line = 'машина %02d | IP %s | аккаунт не задан (нет секрета ARENA_ACC_%02d)' % (SLOT, ip or '?', SLOT)
        print(line)
        tg(line)
        return
    email, _, pwd = PAIR.partition(':')
    st, body, cookies = post_json('https://arena.ai/nextjs-api/sign-in/email',
                                  {'email': email, 'password': pwd},
                                  {'user-agent': UA, 'origin': 'https://arena.ai',
                                   'referer': 'https://arena.ai/login'})
    tok = token_from(cookies)
    me_code, me_body = -1, '{}'
    if tok:
        try:
            me_code, me_body = get_json('https://arena.ai/api/me',
                                        {'authorization': 'Bearer ' + tok, 'user-agent': UA})
        except Exception as e:
            me_body = str(e)
    state = {'slot': SLOT, 'email': email, 'ip': ip, 'login_status': st,
             'me_status': me_code, 'token': tok,
             'cookie': '; '.join(c.split(';')[0] for c in cookies)}
    with open('slot-%02d.json' % SLOT, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False)
    mem = memory_ping(TASK)
    line = 'машина %02d | IP %s | %s | вход %s | /api/me %s | %s' % (SLOT, ip or '?', email, st, me_code, mem)
    print(line)
    tg(line)


if __name__ == '__main__':
    main()
