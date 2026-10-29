#!/usr/bin/env python3
"""Одна машина = один аккаунт = один IP. Вход, проверка, отчёт в Telegram."""
import base64
import json
import os
import re
import urllib.parse
import urllib.request

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
SLOT = int(os.environ.get('SLOT', '0'))
PAIR = os.environ.get('A%02d' % SLOT, '') or ''
TG_TOKEN = os.environ.get('TG_TOKEN', '')
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
    line = 'машина %02d | IP %s | %s | вход %s | /api/me %s' % (SLOT, ip or '?', email, st, me_code)
    print(line)
    tg(line)


if __name__ == '__main__':
    main()
