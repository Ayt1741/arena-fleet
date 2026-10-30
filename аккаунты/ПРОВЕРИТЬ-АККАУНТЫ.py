# -*- coding: utf-8 -*-
"""Проверка и приём аккаунтов Arena.

Читает два источника:
  1) .ФЛОТ-флот/память/АККАУНТЫ.json  — то, что уже накоплено;
  2) АККАУНТЫ-НОВЫЕ.txt               — куда заказчик вставляет новые строки: почта и пароль.

Для каждой пары делает живой вход POST /nextjs-api/sign-in/email,
затем проверяет токен через /api/me, приводит оба файла в порядок
и складывает результат в бота. Ничего не выдумывает: пишет ровно код ответа.

Запуск:  ПРОВЕРИТЬ-АККАУНТЫ.cmd        (или  python ПРОВЕРИТЬ-АККАУНТЫ.py)
"""
import json
import os
import re
import sys
import time
import base64
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
MEM = os.path.join(HERE, '.ФЛОТ-флот', 'память')
F_JSON = os.path.join(MEM, 'АККАУНТЫ.json')
F_NEW = os.path.join(HERE, 'АККАУНТЫ-НОВЫЕ.txt')
F_LOG = os.path.join(HERE, 'ЛОГ-АККАУНТОВ.txt')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')


def sign_in(email, pw):
    """Возвращает (код, токен, текст ошибки)."""
    body = json.dumps({'email': email, 'password': pw}).encode()
    r = urllib.request.Request('https://arena.ai/nextjs-api/sign-in/email', data=body, method='POST')
    for k, v in {'content-type': 'application/json', 'user-agent': UA,
                 'origin': 'https://arena.ai', 'referer': 'https://arena.ai/text'}.items():
        r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, timeout=45) as x:
            raw = ''
            for c in x.headers.get_all('Set-Cookie') or []:
                name, rest = c.split('=', 1)
                if name == 'arena-auth-prod-v1.0':
                    raw = rest.split(';')[0]
                if name == 'arena-auth-prod-v1.1':
                    raw += rest.split(';')[0]
            x.read()
        tok = ''
        if raw:
            r2 = raw[7:] if raw.startswith('base64-') else raw
            try:
                tok = json.loads(base64.b64decode(r2 + '=' * (-len(r2) % 4)).decode())['access_token']
            except Exception:
                tok = ''
        return 200, tok, ''
    except urllib.error.HTTPError as e:
        return e.code, '', e.read().decode('utf-8', 'ignore')[:160]
    except Exception as e:
        return -1, '', str(e)[:160]


def me(tok):
    if not tok:
        return -1, {}
    r = urllib.request.Request('https://arena.ai/api/me',
                               headers={'authorization': 'Bearer ' + tok, 'user-agent': UA})
    try:
        with urllib.request.urlopen(r, timeout=30) as x:
            return x.status, json.loads(x.read().decode()).get('user', {})
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception:
        return -1, {}


def read_new():
    """Строки вида 'почта пароль' (разделитель — пробел, точка с запятой, запятая или табуляция)."""
    out = []
    if not os.path.exists(F_NEW):
        return out
    for line in open(F_NEW, encoding='utf-8-sig'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = re.split(r'[\s;,\t]+', line)
        if len(parts) < 2:
            continue
        email = parts[0]
        pw = line[len(email):].strip().lstrip(';,').strip()
        if '@' in email and pw:
            out.append((email, pw))
    return out


def main():
    acc = json.load(open(F_JSON, encoding='utf-8')) if os.path.exists(F_JSON) else []
    by_mail = {a['email'].lower(): a for a in acc}
    queue = [(a['email'], a['pass'], 'файл') for a in acc]
    known = {a['email'].lower() for a in acc}
    for e, p in read_new():
        if e.lower() in known:
            by_mail[e.lower()]['pass'] = p          # новый пароль перекрывает старый
        else:
            queue.append((e, p, 'новый'))
            known.add(e.lower())

    ts = time.strftime('%d.%m.%Y %H:%M')
    print('=' * 74)
    print('ПРОВЕРКА АККАУНТОВ ARENA — %s' % ts)
    print('=' * 74)
    lines, ok = [], 0
    for i, (email, pw, src) in enumerate(queue, 1):
        st, tok, err = sign_in(email, pw)
        mst, user = me(tok) if st == 200 else (-1, {})
        good = st == 200 and mst == 200
        ok += good
        print('%-2d %-30s вход %-4s /api/me %-4s %s' % (i, email, st, mst, 'РАБОТАЕТ' if good else err[:60]))
        rec = {'n': i, 'email': email, 'pass': pw,
               'status': ('вход 200, /api/me 200 (проверено %s)' % ts) if good
                         else ('НЕТ ВХОДА: вход %s, /api/me %s, %s (проверено %s)' % (st, mst, err[:60], ts))}
        if user.get('email'):
            rec['user'] = user['email']
        by_mail[email.lower()] = rec
        lines.append('%s\t%s\t%s\t%s' % (email, 'ДА' if good else 'нет', st, mst))
        if not good and st in (401, 400):
            print('     → аккаунта с таким паролем нет. Создать: arena.ai → Create account → этот адрес;')
            print('       затем письмо в почте → задать пароль. После этого запусти этот файл снова.')
        time.sleep(1)

    merged = sorted(by_mail.values(), key=lambda a: (a['email'] != 'fsazb21@mail.ru', a.get('n', 99)))
    for i, a in enumerate(merged, 1):
        a['n'] = i
    json.dump(merged, open(F_JSON, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    with open(F_LOG, 'w', encoding='utf-8') as f:
        f.write('Проверка %s\nпочта\tвход\tкод входа\tкод /api/me\n' % ts + '\n'.join(lines) + '\n')
    print('-' * 74)
    print('ИТОГ: работают %d из %d. База обновлена: %s' % (ok, len(queue), F_JSON))
    print('Лог: %s' % F_LOG)
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('m', os.path.join(MEM, 'MEMORY.py'))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        r = m.tg_put(F_LOG, 'проверка аккаунтов %s: %d из %d' % (ts, ok, len(queue)))
        print('В бота: %s' % r['file'])
    except Exception as e:
        print('В бота не ушло: %s' % str(e)[:100])
    return 0 if ok == len(queue) else 1


if __name__ == '__main__':
    sys.exit(main())
