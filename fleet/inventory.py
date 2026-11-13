#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ИНВЕНТАРИЗАЦИЯ АРЕНЫ: список моделей отовсюду, где он виден.

1) Side by Side — два выбираемых списка моделей (там имена есть, в Battle их нет).
2) Рейтинг /leaderboard/text и /leaderboard/code — с локального IP режет Cloudflare,
   с IP машины флота открывается.
3) Direct — полный список (18 моделей).

Результат: JSON со всеми найденными именами, отдельно — все muse-модели.
"""
import asyncio
import base64
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.request

os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', os.path.expanduser('~/.cache/ms-playwright'))
if not list(pathlib.Path(os.environ['PLAYWRIGHT_BROWSERS_PATH']).glob('chromium-*/chrome-linux*/chrome')):
    subprocess.run([sys.executable, '-m', 'playwright', 'install', 'chromium'], check=False)

from playwright.async_api import async_playwright

SLOT = int(os.environ.get('SLOT', '1'))
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


def log(r):
    print(json.dumps(r, ensure_ascii=False), flush=True)


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


async def открыть_список(pg):
    for надпись in ('Max', 'Router', 'Select model', 'Choose a model'):
        к = pg.get_by_role('button', name=надпись, exact=False).first
        if await к.count():
            try:
                await к.click(timeout=7000)
                await pg.wait_for_timeout(2200)
                if await pg.query_selector_all('[role=option]'):
                    return True
            except Exception:
                pass
    for текст in ('Max', 'Router'):
        эл = pg.get_by_text(текст, exact=True).last
        if await эл.count():
            try:
                await эл.click(timeout=7000)
                await pg.wait_for_timeout(2200)
                if await pg.query_selector_all('[role=option]'):
                    return True
            except Exception:
                pass
    return False


async def забрать_опции(pg):
    список = []
    for e in await pg.query_selector_all('[role=option]'):
        t = (await e.inner_text()).strip().split('\n')[0].strip()
        if t and len(t) < 120:
            список.append(t)
    return список


async def основной():
    token, cookies, payload = sign_in(EMAIL, PASS)
    log({'event': 'sign_in', 'user': (payload.get('user') or {}).get('email')})
    итог = {'slot': SLOT, 'account': '%02d' % ACC, 'lists': {}, 'leaderboards': {}}
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        ctx = await b.new_context(locale='en-US', timezone_id='Europe/Moscow', user_agent=UA,
                                  viewport={'width': 1500, 'height': 950})
        await ctx.add_cookies(cookies)
        pg = await ctx.new_page()

        # 1) Direct — полный список
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
                await к.click(timeout=7000)
                await pg.wait_for_timeout(3000)
            except Exception:
                pass
        if await открыть_список(pg):
            итог['lists']['direct'] = await забрать_опции(pg)
            log({'event': 'direct', 'count': len(итог['lists']['direct'])})

        # 2) Side by Side — два списка
        try:
            await pg.goto('https://arena.ai/text', wait_until='domcontentloaded', timeout=90000)
            await pg.wait_for_timeout(6000)
            sbs = pg.get_by_role('button', name='Side by Side', exact=False).first
            if await sbs.count():
                await sbs.click(timeout=8000)
                await pg.wait_for_timeout(4000)
                итог['lists']['sbs_все'] = await забрать_опции(pg)
                log({'event': 'sbs', 'count': len(итог['lists'].get('sbs_все') or [])})
        except Exception as e:
            log({'event': 'sbs_fail', 'err': str(e)[:80]})

        # 3) Рейтинги
        for имя, адрес in (('lb_text', 'https://arena.ai/leaderboard/text'),
                           ('lb_code', 'https://arena.ai/leaderboard/code')):
            try:
                await pg.goto(адрес, wait_until='domcontentloaded', timeout=90000)
                await pg.wait_for_timeout(9000)
                txt = await pg.inner_text('body')
                итог['leaderboards'][имя] = txt[:20000]
                log({'event': имя, 'chars': len(txt),
                     'head': txt[:120].replace('\n', ' | ')})
            except Exception as e:
                log({'event': 'lb_fail', 'name': имя, 'err': str(e)[:80]})
        await pg.screenshot(path='inv-%02d.png' % SLOT)
        await b.close()

    всё = []
    for v in итог['lists'].values():
        всё.extend(v or [])
    for v in итог['leaderboards'].values():
        всё.extend(re.findall(r'[A-Za-z0-9\.\- ]{0,14}[Mm]use[A-Za-z0-9\.\- ]{0,25}', v))
    итог['muse'] = sorted(set(x.strip() for x in всё if 'muse' in x.lower()))
    итог['все_уникальные'] = sorted(set(x.strip() for x in всё if x.strip()))
    json.dump(итог, open('inv-%02d.json' % SLOT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    log({'event': 'finish', 'muse': итог['muse'], 'уникальных': len(итог['все_уникальные'])})


asyncio.run(основной())
