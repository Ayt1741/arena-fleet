# -*- coding: utf-8 -*-
"""ВХОД В АККАУНТЫ ARENA — настоящий вход, не проверка.

Для каждой пары почта/пароль:
  1) POST /nextjs-api/sign-in/email  → живые cookie сессии;
  2) GET  /api/me                    → кто вошёл (id, почта, способ входа);
  3) GET  /api/history/unified       → сколько чатов видит аккаунт;
  4) сохраняет сессию в папку ВХОДЫ/  (видно в корне, формат: cookie для браузера + токен);
  5) пишет итог в ЛОГ-ВХОДОВ.txt и отправляет в бота.

Аккаунты берёт из .ФЛОТ-флот/память/АККАУНТЫ.json и из АККАУНТЫ-НОВЫЕ.txt.
Можно указать конкретные почты:  python ВОЙТИ.py sanya.dovlatov.98@mail.ru

Запуск: ВОЙТИ.cmd
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
MEM = os.path.join(HERE, '.ФЛОТ-флот', 'память')
OUT = os.path.join(HERE, 'ВХОДЫ')
F_JSON = os.path.join(MEM, 'АККАУНТЫ.json')
F_NEW = os.path.join(HERE, 'АККАУНТЫ-НОВЫЕ.txt')
F_LOG = os.path.join(HERE, 'ЛОГ-ВХОДОВ.txt')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')


def _post(url, body, extra=None):
    r = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST')
    hdr = {'content-type': 'application/json', 'user-agent': UA,
           'origin': 'https://arena.ai', 'referer': 'https://arena.ai/text'}
    hdr.update(extra or {})
    for k, v in hdr.items():
        r.add_header(k, v)
    return r


def _get(url, tok=None):
    r = urllib.request.Request(url, headers={'user-agent': UA,
                                             **({'authorization': 'Bearer ' + tok} if tok else {})})
    return r


def sign_in(email, pw, tries=3):
    """→ (код, cookie-dict, access_token, ошибка)"""
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(_post('https://arena.ai/nextjs-api/sign-in/email',
                                              {'email': email, 'password': pw}), timeout=45) as x:
                ck = {}
                for c in x.headers.get_all('Set-Cookie') or []:
                    name, rest = c.split('=', 1)
                    ck[name] = rest.split(';')[0]
                x.read()
            raw = ck.get('arena-auth-prod-v1.0', '') + ck.get('arena-auth-prod-v1.1', '')
            tok = ''
            if raw:
                r2 = raw[7:] if raw.startswith('base64-') else raw
                try:
                    tok = json.loads(base64.b64decode(r2 + '=' * (-len(r2) % 4)).decode())['access_token']
                except Exception:
                    tok = ''
            return 200, ck, tok, ''
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', 'ignore')[:160]
            if e.code == 429 and attempt < tries - 1:
                print('     429 — лимит попыток, жду 25 с')
                time.sleep(25)
                continue
            return e.code, {}, '', body
        except Exception as e:
            return -1, {}, '', str(e)[:160]
    return -1, {}, '', 'не удалось'


def api(url, tok):
    try:
        with urllib.request.urlopen(_get(url, tok), timeout=45) as x:
            return x.status, json.loads(x.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception:
        return -1, {}


def accounts(only=None):
    out = []
    if os.path.exists(F_JSON):
        for a in json.load(open(F_JSON, encoding='utf-8')):
            out.append((a['email'], a['pass']))
    if os.path.exists(F_NEW):
        for line in open(F_NEW, encoding='utf-8-sig'):
            line = line.strip()
            if not line or line.startswith('#') or '@' not in line:
                continue
            email = line.split()[0]
            pw = line[len(email):].strip().lstrip(';, ').strip()
            if pw:
                out.append((email, pw))
    seen, uniq = set(), []
    for e, p in out:
        if e.lower() in seen:
            continue
        seen.add(e.lower())
        uniq.append((e, p))
    if only:
        low = [o.lower() for o in only]
        uniq = [(e, p) for e, p in uniq if e.lower() in low]
    return uniq


def main():
    only = [a for a in sys.argv[1:] if '@' in a]
    os.makedirs(OUT, exist_ok=True)
    ts = time.strftime('%d.%m.%Y %H:%M')
    print('=' * 78)
    print('ВХОД В АККАУНТЫ ARENA — %s' % ts)
    print('=' * 78)
    lines, ok = [], 0
    for i, (email, pw) in enumerate(accounts(only), 1):
        st, ck, tok, err = sign_in(email, pw)
        if st != 200:
            print('%-2d %-30s вход %-4s %s' % (i, email, st, err[:60]))
            lines.append('%s\tНЕТ ВХОДА\t%s\t%s' % (email, st, err[:60]))
            time.sleep(2)
            continue
        mst, me = api('https://arena.ai/api/me', tok)
        hst, hist = api('https://arena.ai/api/history/unified', tok)
        user = me.get('user', {})
        chats = len(hist.get('entries') or [])
        good = mst == 200 and bool(tok)
        ok += good
        print('%-2d %-30s ВОШЁЛ | /api/me %s | чатов %s | токен %d симв. | id %s'
              % (i, email, mst, chats, len(tok), (user.get('id') or '-')[:8]))
        rec = {'email': email, 'password': pw, 'ts': ts,
               'me_status': mst, 'user': user, 'chats': chats,
               'access_token': tok,
               'cookie_header': '; '.join('%s=%s' % (k, v) for k, v in ck.items()),
               'cookies': ck}
        name = ('%02d-' % i) + email.replace('@', '_at_').replace('/', '_') + '.json'
        json.dump(rec, open(os.path.join(OUT, name), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        lines.append('%s\tВОШЁЛ\t/api/me %s\tчатов %s\tid %s\t%s' % (email, mst, chats, (user.get('id') or '-')[:8], name))
        time.sleep(2)

    with open(F_LOG, 'w', encoding='utf-8') as f:
        f.write('Вход в аккаунты %s\nпочта\tитог\t/api/me\tчатов\tid\tфайл\n' % ts + '\n'.join(lines) + '\n')
    print('-' * 78)
    print('ИТОГ: вошли %d из %d. Сессии в папке ВХОДЫ (%d файлов).' % (ok, len(accounts(only)), len(os.listdir(OUT))))
    print('Лог: %s' % F_LOG)
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('m', os.path.join(MEM, 'MEMORY.py'))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        print('В бота: %s' % m.tg_put(F_LOG, 'вход в аккаунты %s: %d из %d' % (ts, ok, len(accounts(only))))['file'])
    except Exception as e:
        print('В бота не ушло: %s' % str(e)[:100])
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
