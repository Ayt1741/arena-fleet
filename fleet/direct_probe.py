#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""СОВЕТ В DIRECT: каждая машина спрашивает у конкретной модели и присылает ответ.

Зачем: в Battle модели анонимны — кто ответил, не видно. Сравнивать конкретные
модели по коду можно только в Direct, где имя выбирается рукой. Машина делает
ровно одну задачу: выбрать модель по имени, задать ей целевой вопрос, забрать ответ.

  SLOT=1 MODEL=claude-sonnet-5-5-high TASK="..." python3 direct_probe.py
"""
import asyncio
import base64
import json
import os
import pathlib
import random
import subprocess
import sys
import time
import urllib.request

os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', os.path.expanduser('~/.cache/ms-playwright'))
if not list(pathlib.Path(os.environ['PLAYWRIGHT_BROWSERS_PATH']).glob('chromium-*/chrome-linux*/chrome')):
    subprocess.run([sys.executable, '-m', 'playwright', 'install', 'chromium'], check=False)

from playwright.async_api import async_playwright

SLOT = int(os.environ.get('SLOT', '1'))
MODEL = os.environ.get('MODEL', '').strip()
TASK = os.environ.get('TASK', '').strip()
ROLE = os.environ.get('ROLE', '').strip()
TG_TOKEN = os.environ.get('TG_TOKEN', '').strip()
TG_CHAT = os.environ.get('TG_CHAT', '7023156818').strip()
WAIT = int(os.environ.get('WAIT', '200'))
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/126.0.0.0 Safari/537.36')
ACC = ((SLOT - 1) % 10) + 1
EMAIL = os.environ.get('ARENA_EMAIL', '').strip()
PASS = os.environ.get('ARENA_PASS', '').strip()
if not EMAIL:
    _pair = os.environ.get('A%02d' % ACC, '').strip()
    if ':' in _pair:
        EMAIL, PASS = _pair.split(':', 1)
    elif '|' in _pair:
        EMAIL, PASS = _pair.split('|', 1)


def log(rec):
    print(json.dumps(rec, ensure_ascii=False), flush=True)


def push(text, click=''):
    if not TG_TOKEN:
        return
    try:
        data = {'chat_id': TG_CHAT, 'text': text[:3800], 'disable_web_page_preview': True}
        if click:
            data['reply_markup'] = json.dumps({'inline_keyboard': [[{'text': 'открыть диалог', 'url': click}]]})
        r = urllib.request.Request('https://api.telegram.org/bot%s/sendMessage' % TG_TOKEN,
                                   data=json.dumps(data).encode(), method='POST')
        r.add_header('Content-Type', 'application/json')
        urllib.request.urlopen(r, timeout=60).read()
    except Exception as e:
        log({'event': 'tg_error', 'msg': str(e)[:80]})


def sign_in(email, password, tries=4):
    last = None
    for i in range(tries):
        try:
            body = json.dumps({'email': email, 'password': password}).encode()
            r = urllib.request.Request('https://arena.ai/nextjs-api/sign-in/email', data=body, method='POST')
            for k, v in {'content-type': 'application/json', 'user-agent': UA,
                         'origin': 'https://arena.ai', 'referer': 'https://arena.ai/direct'}.items():
                r.add_header(k, v)
            with urllib.request.urlopen(r, timeout=45) as x:
                cookies = []
                for c in x.headers.get_all('Set-Cookie') or []:
                    name, rest = c.split('=', 1)
                    cookies.append((name, rest.split(';')[0]))
                payload = json.loads(x.read().decode())
            raw = ''.join(v for n, v in cookies if n.startswith('arena-auth'))
            raw = raw[7:] if raw.startswith('base64-') else raw
            js = json.loads(base64.b64decode(raw + '=' * (-len(raw) % 4)).decode())
            return js.get('access_token', ''), [
                {'name': 'arena-auth-prod-v1.0', 'value': 'base64-' + raw[:len(raw) // 2],
                 'domain': 'arena.ai', 'path': '/'},
                {'name': 'arena-auth-prod-v1.1', 'value': raw[len(raw) // 2:],
                 'domain': 'arena.ai', 'path': '/'}], payload
        except Exception as e:
            last = e
            log({'event': 'sign_in_retry', 'try': i + 1, 'err': str(e)[:100]})
            time.sleep(10 * (i + 1))
    raise last


def accept_terms(token):
    r = urllib.request.Request('https://arena.ai/api/me/update-tou-consent', data=b'{}', method='POST')
    for k, v in {'authorization': 'Bearer ' + token, 'content-type': 'application/json',
                 'user-agent': UA, 'origin': 'https://arena.ai', 'referer': 'https://arena.ai/direct'}.items():
        r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, timeout=40) as x:
            return x.status
    except Exception as e:
        return str(e)[:80]


async def api(pg, path):
    return await pg.evaluate("""async (p) => {
        const r = await fetch(p, {headers:{'accept':'application/json'}});
        if (!r.ok) return {status:r.status, entries:[], data:[]};
        const j = await r.json(); j.status = r.status; return j;
    }""", path)


async def открыть_список(pg):
    """Открыть выпадающий список моделей и вернуть его элементы."""
    for надпись in ('Max', 'Router', 'Select model', 'Choose a model'):
        к = pg.get_by_role('button', name=надпись, exact=False).first
        if await к.count():
            try:
                await к.click(timeout=8000)
                await pg.wait_for_timeout(2500)
                if await pg.query_selector_all('[role=option]'):
                    return True
            except Exception:
                pass
    for текст in ('Max', 'Router'):
        эл = pg.get_by_text(текст, exact=True).last
        if await эл.count():
            try:
                await эл.click(timeout=8000)
                await pg.wait_for_timeout(2500)
                if await pg.query_selector_all('[role=option]'):
                    return True
            except Exception:
                pass
    return False


async def выбрать_модель(pg, модель):
    if not await открыть_список(pg):
        return False
    for e in await pg.query_selector_all('[role=option]'):
        t = (await e.inner_text()).strip().split('\n')[0].strip()
        if t == модель:
            await e.click(timeout=8000)
            return True
    поиск = pg.get_by_placeholder('Search models').first
    if await поиск.count():
        await поиск.click(timeout=6000)
        await поиск.fill(модель)
        await pg.wait_for_timeout(2500)
        for e in await pg.query_selector_all('[role=option]'):
            t = (await e.inner_text()).strip().split('\n')[0].strip()
            if t == модель:
                await e.click(timeout=8000)
                return True
    return False


async def main():
    log({'event': 'start', 'slot': SLOT, 'account': '%02d' % ACC, 'model': MODEL, 'role': ROLE})
    token, cookies, payload = sign_in(EMAIL, PASS)
    log({'event': 'sign_in', 'user': (payload.get('user') or {}).get('email')})
    log({'event': 'terms_api', 'result': accept_terms(token)})
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=os.environ.get('HEADLESS', '1') != '0',
                                     args=['--no-sandbox', '--disable-dev-shm-usage',
                                           '--disable-blink-features=AutomationControlled'])
        ctx = await b.new_context(locale='en-US', timezone_id='Europe/Moscow', user_agent=UA,
                                  viewport={'width': random.choice([1366, 1400, 1440]),
                                            'height': random.choice([768, 900])})
        await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        await ctx.add_cookies(cookies)
        pg = await ctx.new_page()
        await pg.goto('https://arena.ai/direct', wait_until='domcontentloaded', timeout=90000)
        for _ in range(40):
            await pg.wait_for_timeout(1500)
            if await pg.locator('textarea').count():
                break
            if await pg.get_by_role('button', name='Direct', exact=False).count():
                break
        await pg.wait_for_timeout(2500)
        к = pg.get_by_role('button', name='Direct', exact=False).first
        if await к.count():
            try:
                await к.click(timeout=8000)
                await pg.wait_for_timeout(3000)
            except Exception:
                pass
        await pg.wait_for_timeout(2000)
        # весь список моделей — попутно
        список = []
        if await открыть_список(pg):
            for e in await pg.query_selector_all('[role=option]'):
                t = (await e.inner_text()).strip().split('\n')[0].strip()
                if t and len(t) < 120:
                    список.append(t)
            log({'event': 'models_seen', 'count': len(список), 'models': список})
        if MODEL.startswith('LIST'):
            # режим инвентаризации: модель не выбираем, только собираем список
            режим = MODEL
            json.dump({'slot': SLOT, 'account': '%02d' % ACC, 'mode': режим,
                       'models': список, 'count': len(список),
                       'muse': [m for m in список if 'muse' in m.lower()],
                       'task': TASK, 'ok': bool(список)},
                      open('probe-%02d.json' % SLOT, 'w', encoding='utf-8'),
                      ensure_ascii=False, indent=1)
            log({'event': 'list_mode', 'mode': режим, 'count': len(список),
                 'muse': [m for m in список if 'muse' in m.lower()]})
            push('СПИСОК #%02d | %s\nвсего моделей: %d\nmuse: %s\n\n%s' %
                 (SLOT, режим, len(список),
                  ', '.join(m for m in список if 'muse' in m.lower()) or 'нет',
                  '\n'.join(список)))
            await pg.screenshot(path='probe-%02d.png' % SLOT)
            await b.close()
            return
        выбрана = await выбрать_модель(pg, MODEL)
        log({'event': 'model_pick', 'model': MODEL, 'ok': выбрана})
        if not выбрана:
            await pg.screenshot(path='fail-model-%02d.png' % SLOT)
            json.dump({'slot': SLOT, 'model': MODEL, 'task': TASK, 'ok': False,
                       'error': 'модель не выбрана', 'models': список},
                      open('probe-%02d.json' % SLOT, 'w', encoding='utf-8'),
                      ensure_ascii=False, indent=1)
            await b.close()
            return
        await pg.wait_for_timeout(2500)
        base = {e.get('id') for e in (await api(pg, '/api/history/unified?limit=20&includeArchived=false')).get('entries', [])}
        коробка = pg.locator('textarea').first
        await коробка.click(timeout=25000)
        await коробка.fill(TASK)
        await pg.wait_for_timeout(800)
        await коробка.press('Enter')
        диалог = None
        for _ in range(15):
            await pg.wait_for_timeout(5000)
            ents = (await api(pg, '/api/history/unified?limit=20&includeArchived=false')).get('entries', [])
            new = [e for e in ents if e.get('id') not in base]
            if new:
                диалог = new[0].get('id')
                break
        log({'event': 'sent', 'dialog': диалог})
        ответ = ''
        if диалог:
            for _ in range(40):
                await pg.wait_for_timeout(6000)
                got = await api(pg, '/api/chat/%s/messages?limit=50' % диалог)
                msgs = got.get('data') or got.get('messages') or got.get('entries') or []
                куски = []
                for m in msgs:
                    role = m.get('role') or m.get('author') or ''
                    c = m.get('content') or m.get('text') or ''
                    if isinstance(c, list):
                        c = ' '.join(str(x.get('text', '')) if isinstance(x, dict) else str(x) for x in c)
                    if role not in ('user',) and c:
                        куски.append(c)
                if куски:
                    ответ = '\n\n'.join(куски)
                    if len(ответ) > 400:
                        break
        if not ответ:
            текст = await pg.inner_text('body')
            i = текст.find(TASK[:40])
            if i >= 0:
                ответ = текст[i + len(TASK):].strip()
        log({'event': 'collected', 'chars': len(ответ)})
        ссылка = 'https://arena.ai/c/%s' % диалог if диалог else ''
        rec = {'slot': SLOT, 'account': '%02d' % ACC, 'model': MODEL, 'role': ROLE,
               'task': TASK, 'ok': bool(ответ), 'chars': len(ответ),
               'dialog': диалог, 'link': ссылка, 'answer': ответ[:12000],
               'models_seen': список}
        json.dump(rec, open('probe-%02d.json' % SLOT, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        push('DIRECT #%02d | %s | роль: %s\n%s\n\n%s\n\nссылка: %s' %
             (SLOT, MODEL, ROLE or '-', TASK[:400], (ответ[:2500] or 'ответа нет'), ссылка), click=ссылка)
        await pg.screenshot(path='probe-%02d.png' % SLOT)
        await b.close()
        log({'event': 'finish', 'ok': bool(ответ)})


if __name__ == '__main__':
    asyncio.run(main())
