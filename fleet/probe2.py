#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ОПРОС МОДЕЛЕЙ — два пути, потому что один заблокирован.

Путь BATTLE: арена принимает сообщение, модели анонимны. Чтобы узнать, кто ответил,
нужно проголосовать — после голосования арена раскрывает имена моделей.
Путь DIRECT: имена видно сразу, но отправка упирается в recaptcha (403
"recaptcha validation failed"). Поэтому DIRECT идёт в headful-браузере под xvfb.

  MODE=battle python3 probe2.py
  MODE=direct python3 probe2.py
"""
import asyncio
import base64
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request

os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', os.path.expanduser('~/.cache/ms-playwright'))
if not list(pathlib.Path(os.environ['PLAYWRIGHT_BROWSERS_PATH']).glob('chromium-*/chrome-linux*/chrome')):
    subprocess.run([sys.executable, '-m', 'playwright', 'install', 'chromium'], check=False)

from playwright.async_api import async_playwright

SLOT = int(os.environ.get('SLOT', '1'))
MODE = os.environ.get('MODE', 'battle').strip().lower()
ACC = ((SLOT - 1) % 10) + 1
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/126.0.0.0 Safari/537.36')
EMAIL = os.environ.get('ARENA_EMAIL', '')
PASS = os.environ.get('ARENA_PASS', '')
if not EMAIL:
    _p = os.environ.get('A%02d' % ACC, '').strip()
    if ':' in _p:
        EMAIL, PASS = _p.split(':', 1)
    elif '|' in _p:
        EMAIL, PASS = _p.split('|', 1)
TASK_FILE = os.environ.get('TASK_FILE', '').strip()
МОДЕЛЬ = os.environ.get('MODEL', '').strip()
ВОПРОС = os.environ.get('Q', '').strip()
РОЛЬ = os.environ.get('ROLE', '').strip()
TG_TOKEN = os.environ.get('TG_TOKEN', '').strip()
TG_CHAT = os.environ.get('TG_CHAT', '7023156818').strip()
HEADFUL = os.environ.get('HEADFUL', '0') == '1'


def log(r):
    print(json.dumps(r, ensure_ascii=False), flush=True)


def push(text):
    if not TG_TOKEN:
        return
    try:
        data = {'chat_id': TG_CHAT, 'text': text[:3800], 'disable_web_page_preview': True}
        r = urllib.request.Request('https://api.telegram.org/bot%s/sendMessage' % TG_TOKEN,
                                   data=json.dumps(data).encode(), method='POST')
        r.add_header('Content-Type', 'application/json')
        urllib.request.urlopen(r, timeout=60).read()
    except Exception as e:
        log({'event': 'tg_error', 'msg': str(e)[:80]})


def sign_in(email, password, tries=3):
    last = None
    for i in range(tries):
        try:
            body = json.dumps({'email': email, 'password': password}).encode()
            r = urllib.request.Request('https://arena.ai/nextjs-api/sign-in/email', data=body, method='POST')
            for k, v in {'content-type': 'application/json', 'user-agent': UA,
                         'origin': 'https://arena.ai', 'referer': 'https://arena.ai/text'}.items():
                r.add_header(k, v)
            with urllib.request.urlopen(r, timeout=45) as x:
                ck = []
                for c in x.headers.get_all('Set-Cookie') or []:
                    n, rest = c.split('=', 1)
                    ck.append((n, rest.split(';')[0]))
                payload = json.loads(x.read().decode())
            raw = ''.join(v for n, v in ck if n.startswith('arena-auth'))
            raw = raw[7:] if raw.startswith('base64-') else raw
            js = json.loads(base64.b64decode(raw + '=' * (-len(raw) % 4)).decode())
            return js.get('access_token', ''), [
                {'name': 'arena-auth-prod-v1.0', 'value': 'base64-' + raw[:len(raw) // 2],
                 'domain': 'arena.ai', 'path': '/'},
                {'name': 'arena-auth-prod-v1.1', 'value': raw[len(raw) // 2:],
                 'domain': 'arena.ai', 'path': '/'}], payload
        except Exception as e:
            last = e
            log({'event': 'sign_in_retry', 'err': str(e)[:120]})
            time.sleep(8 * (i + 1))
    raise last


def accept_terms(token):
    r = urllib.request.Request('https://arena.ai/api/me/update-tou-consent', data=b'{}', method='POST')
    for k, v in {'authorization': 'Bearer ' + token, 'content-type': 'application/json',
                 'user-agent': UA, 'origin': 'https://arena.ai', 'referer': 'https://arena.ai/text'}.items():
        r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, timeout=40) as x:
            return x.status
    except Exception as e:
        return str(e)[:80]


async def api(pg, path):
    return await pg.evaluate("""async (p) => {
        const r = await fetch(p, {headers:{'accept':'application/json'}});
        if (!r.ok) return {status:r.status, body:(await r.text()).slice(0,400)};
        const t = await r.text();
        try { return Object.assign({status:r.status}, JSON.parse(t)); }
        catch(e) { return {status:r.status, body:t.slice(0,400)}; }
    }""", path)


async def ждать_гидратации(pg):
    for _ in range(40):
        await pg.wait_for_timeout(1500)
        if await pg.locator('textarea').count():
            return True
        if await pg.get_by_role('button', name='Battle', exact=False).count():
            return True
    return False


async def основной():
    if TASK_FILE and os.path.exists(TASK_FILE):
        t = json.load(open(TASK_FILE, encoding='utf-8'))
        ВОПРОС = str(t.get('task') or ВОПРОС)
        МОДЕЛЬ = str(t.get('model') or МОДЕЛЬ)
        РОЛЬ = str(t.get('role') or РОЛЬ)
    token, cookies, payload = sign_in(EMAIL, PASS)
    log({'event': 'sign_in', 'user': (payload.get('user') or {}).get('email')})
    log({'event': 'terms', 'result': accept_terms(token)})
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=not HEADFUL,
                                     args=['--no-sandbox', '--disable-dev-shm-usage',
                                           '--disable-blink-features=AutomationControlled'])
        ctx = await b.new_context(locale='en-US', timezone_id='Europe/Moscow', user_agent=UA,
                                  viewport={'width': 1440, 'height': 900})
        await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        await ctx.add_cookies(cookies)
        pg = await ctx.new_page()
        ошибки = []

        async def ловить(resp):
          try:
            u = resp.url
            if 'arena.ai' not in u or 'analytics' in u or 'google' in u:
                return
            if not any(k in u for k in ('/api/', '/nextjs-api/')):
                return
            if 'history/unified' in u or '/api/me' in u or 'pulse' in u:
                return
            тело = ''
            try:
                тело = (await resp.text())[:500]
            except Exception:
                pass
            ошибки.append({'status': resp.status, 'url': u[:150], 'body': тело[:300]})
          except Exception as e:
            pass

        pg.on('response', lambda r: asyncio.ensure_future(ловить(r)))
        url = 'https://arena.ai/direct' if MODE == 'direct' else 'https://arena.ai/text'
        await pg.goto(url, wait_until='domcontentloaded', timeout=90000)
        await ждать_гидратации(pg)
        await pg.wait_for_timeout(2500)
        режим = MODE
        if MODE == 'direct':
            к = pg.get_by_role('button', name='Direct', exact=False).first
            if await к.count():
                try:
                    await к.click(timeout=8000)
                    await pg.wait_for_timeout(3000)
                except Exception:
                    pass
            for надпись in ('Max', 'Router', 'Select model'):
                b2 = pg.get_by_role('button', name=надпись, exact=False).first
                if await b2.count():
                    try:
                        await b2.click(timeout=8000)
                        await pg.wait_for_timeout(2500)
                        break
                    except Exception:
                        pass
            выбрана = False
            for e in await pg.query_selector_all('[role=option]'):
                t = (await e.inner_text()).strip().split('\n')[0].strip()
                if t == МОДЕЛЬ:
                    await e.click(timeout=8000)
                    выбрана = True
                    break
            log({'event': 'model_pick', 'model': МОДЕЛЬ, 'ok': выбрана})
            await pg.wait_for_timeout(2000)
        else:
            # кнопку Battle не нажимаем: в прогоне совета диалоги создавались без неё,
            # а после клика арена режет отправку на recaptcha
            await pg.wait_for_timeout(4000)
            # после переключения в Battle поле ввода может быть другим — ищем заново
            for _ in range(20):
                if await pg.locator('textarea').count():
                    break
                await pg.wait_for_timeout(1500)
            log({'event': 'textarea', 'count': await pg.locator('textarea').count()})
        base = {e.get('id') for e in (await api(pg, '/api/history/unified?limit=20&includeArchived=false')).get('entries', [])}
        коробка = pg.locator('textarea').first
        await коробка.click(timeout=25000)
        await коробка.fill(ВОПРОС)
        await pg.wait_for_timeout(800)
        await коробка.press('Enter')
        диалог = None
        for _ in range(20):
            await pg.wait_for_timeout(5000)
            ents = (await api(pg, '/api/history/unified?limit=20&includeArchived=false')).get('entries', [])
            new = [e for e in ents if e.get('id') not in base]
            if new:
                диалог = new[0].get('id')
                break
        log({'event': 'sent', 'dialog': диалог})
        # ждём ответы
        ответы = []
        for _ in range(30):
            await pg.wait_for_timeout(6000)
            if диалог:
                got = await api(pg, '/api/chat/%s/messages?limit=50' % диалог)
                msgs = got.get('data') or got.get('messages') or got.get('entries') or []
                for m in msgs:
                    role = m.get('role') or m.get('author') or ''
                    c = m.get('content') or m.get('text') or ''
                    if isinstance(c, list):
                        c = ' '.join(str(x.get('text', '')) if isinstance(x, dict) else str(x) for x in c)
                    if role != 'user' and c:
                        ответы.append({'role': role, 'model': m.get('model') or m.get('modelKey')
                                        or m.get('modelName') or m.get('authorName') or '?',
                                        'content': c})
                if len(ответы) >= 2 and sum(len(r['content']) for r in ответы) > 600:
                    break
            текст = await pg.inner_text('body')
            if 'Something went wrong' in текст:
                log({'event': 'server_error', 'text': текст[:200]})
                break
        log({'event': 'answers', 'count': len(ответы),
             'chars': sum(len(r['content']) for r in ответы)})
        if ответы:
            log({'event': 'answers_dump', 'json': json.dumps(ответы, ensure_ascii=False)[:4000]})
        # в Battle после голосования арена раскрывает имена моделей
        if MODE == 'battle' and диалог:
            for имя in ('A is better', 'Both are good', 'A is better '):
                pass
            try:
                await pg.get_by_text('A is better', exact=False).first.click(timeout=8000)
                await pg.wait_for_timeout(6000)
                log({'event': 'voted'})
            except Exception as e:
                log({'event': 'vote_fail', 'err': str(e)[:80]})
            got = await api(pg, '/api/chat/%s/messages?limit=50' % диалог)
            msgs = got.get('data') or got.get('messages') or got.get('entries') or []
            log({'event': 'after_vote', 'json': json.dumps(msgs, ensure_ascii=False)[:4000]})
        for запись in ошибки[-25:]:
            log({'event': 'http', **запись})
        rec = {'slot': SLOT, 'mode': MODE, 'model': МОДЕЛЬ, 'role': РОЛЬ, 'task': ВОПРОС,
               'dialog': диалог, 'answers': ответы, 'ok': bool(ответы),
               'chars': sum(len(r['content']) for r in ответы)}
        json.dump(rec, open('probe2-%02d.json' % SLOT, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        сводка = '\n\n'.join('[%s] %s' % (r['model'], r['content'][:1500]) for r in ответы[:3])
        push('ОПРОС #%02d | %s | %s | %s\n%s\n\n%s' %
             (SLOT, режим, МОДЕЛЬ or '-', РОЛЬ or '-', ВОПРОС[:300], сводка or 'ответов нет'))
        await pg.screenshot(path='probe2-%02d.png' % SLOT)
        await b.close()
        log({'event': 'finish', 'ok': bool(ответы)})


asyncio.run(основной())
