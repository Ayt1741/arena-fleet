#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""РЕШАТЕЛЬ: 20 машин ищут, как отправлять в арену, и собирают данные по моделям.

Две задачи на машину (по SLOT):
  A) Проверить модель по имени в Direct: выбрать, отправить, забрать ответ.
  B) Обойти recaptcha: собрать, что арена требует для отправки, и доложить.

Если отправку режет recaptcha — машина пробует обход:
  1) ждёт, пока страница полностью прогрузится (recaptcha-enterprise-ready-shim),
  2) выполняет recaptcha-токен вручную через execute(),
  3) пробует отправку через API /nextjs-api/stream/create-evaluation с токеном.

Результат — JSON на машину + сообщение в Telegram.
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
TG_TOKEN = os.environ.get('TG_TOKEN', '').strip()
TG_CHAT = os.environ.get('TG_CHAT', '7023156818').strip()
RECAPTCHA_KEY = os.environ.get('RECAPTCHA_KEY', '').strip()

МОДЕЛИ = [
    "muse-spark-1.3-xhigh", "muse-ember-max", "claude-sonnet-5-5-high",
    "claude-haiku-5.5-high", "gemini-4-argon-high", "gemini-3.8-flash-high",
    "kimi-k3", "grok-4.6-medium", "gpt-6-luna-max", "gpt-6.1-terra-low",
    "deepseek-v4.1-flash-high", "deepseek-v4.1-flash-max", "mimo-v2.6-pro",
    "mimo-v2.6-flash", "glm-5.3-flash", "qwen3.8-27b", "inkling-medium",
]
ВОПРОСЫ = [
    "Напиши на Python функцию merge_sorted(lists) — сливает отсортированные списки в новый отсортированный, исходные не меняет. Дай код и 3 строки пояснения.",
    "Вот лог: ERROR connection pool exhausted; retry in 5s; queue depth 12400; ERROR connection pool exhausted; retry in 5s; queue depth 12890. Назови первопричину и 3 конкретных исправления в коде.",
    "Найди баг и объясни, почему это не работает на пустом списке: def first_even(xs):\n    for i in range(len(xs)):\n        if xs[i] % 2 == 0:\n            return xs[i]\n    return None",
    "Посчитай, сколько раз цифра 7 встречается в числах от 1 до 100 включительно. Покажи ход рассуждения и объясни, почему ответ не 27.",
]


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


async def выбрать(pg, модель):
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


async def токен_recaptcha(pg):
    """Пробуем добыть recaptcha-токен так, как это делает сайт."""
    if not RECAPTCHA_KEY:
        return ''
    try:
        return await pg.evaluate("""async (key) => {
            try {
              if (!window.grecaptcha || !window.grecaptcha.enterprise) return '';
              await new Promise(r => window.grecaptcha.enterprise.ready(r));
              return await new Promise((res) => {
                window.grecaptcha.enterprise.execute(key, {action:'submit'})
                  .then(t => res(t)).catch(() => res(''));
              });
            } catch(e) { return ''; }
        }""", RECAPTCHA_KEY)
    except Exception:
        return ''


ХВОСТ_МУСОР = ("\nDirect\n\nBattle Mode", "\nBattle ModeBattle", "Get More Done With Agents",
               "Terms of Use", "Start evaluating agentic AI", "Try it now", "Hide this",
               "Ask anything", "Thinking...\n\n", "Generating...\n\n")


def разбор_ответа(текст, вопрос):
    """Из страницы достаём только ответ модели: после вопроса и до служебных надписей."""
    i = текст.rfind(вопрос[:40])
    хвост = текст[i + len(вопрос):] if i >= 0 else текст
    for м in ХВОСТ_МУСОР:
        j = хвост.find(м)
        if j >= 0:
            хвост = хвост[:j]
    строки = [с for с in хвост.split("\n") if с.strip()]
    # отбрасываем служебные надписи и эхо вопроса
    чист = []
    for с in строки:
        t = с.strip()
        if not t:
            continue
        if t in ("Direct", "Battle", "Agent Mode", "Side by Side", "Text", "OLDER"):
            continue
        if t.startswith(("Battle ModeBattle", "Agent ModeBuilt", "Side by SideCompare",
                         "DirectChat with 1 model", "Direct\n")):
            continue
        if t.startswith(chr(92) + "u"):
            continue
        if t == вопрос[:60]:
            continue
        чист.append(с)
    return "\n".join(чист).strip()


async def основной():
    модель = МОДЕЛИ[(SLOT - 1) % len(МОДЕЛИ)]
    вопрос = ВОПРОСЫ[(SLOT - 1) % len(ВОПРОСЫ)]
    if TASK_FILE and os.path.exists(TASK_FILE):
        t = json.load(open(TASK_FILE, encoding='utf-8'))
        модель = str(t.get('model') or модель)
        вопрос = str(t.get('task') or вопрос)
    token, cookies, payload = sign_in(EMAIL, PASS)
    log({'event': 'sign_in', 'user': (payload.get('user') or {}).get('email'),
         'model': модель})
    результат = {'slot': SLOT, 'account': '%02d' % ACC, 'model': модель,
                  'question': вопрос, 'ok': False, 'answer': '', 'notes': []}
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage',
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
            if 'arena.ai' not in u:
                return
            if 'create-evaluation' in u or '/stream/' in u:
                try:
                    тело = (await resp.text())[:400]
                except Exception:
                    тело = ''
                ошибки.append({'status': resp.status, 'url': u[:140], 'body': тело[:300]})
          except Exception:
            pass

        pg.on('response', lambda r: asyncio.ensure_future(ловить(r)))
        await pg.goto('https://arena.ai/direct', wait_until='domcontentloaded', timeout=90000)
        for _ in range(40):
            await pg.wait_for_timeout(1500)
            if await pg.locator('textarea').count():
                break
            if await pg.get_by_role('button', name='Direct', exact=False).count():
                break
        await pg.wait_for_timeout(3000)
        к = pg.get_by_role('button', name='Direct', exact=False).first
        if await к.count():
            try:
                await к.click(timeout=8000)
                await pg.wait_for_timeout(3000)
            except Exception:
                pass
        выбрана = await выбрать(pg, модель)
        log({'event': 'model_pick', 'model': модель, 'ok': выбрана})
        результат['model_picked'] = выбрана
        if not выбрана:
            результат['notes'].append('модель не найдена в списке Direct')
            json.dump(результат, open('solv-%02d.json' % SLOT, 'w', encoding='utf-8'),
                      ensure_ascii=False, indent=1)
            await b.close()
            return
        await pg.wait_for_timeout(2000)
        # 1) пробуем отправить как есть
        box = pg.locator('textarea').first
        await box.click(timeout=20000)
        await box.fill(вопрос)
        await pg.wait_for_timeout(700)
        await box.press('Enter')
        for i in range(12):
            await pg.wait_for_timeout(5000)
            txt = await pg.inner_text('body')
            if 'Something went wrong' in txt:
                результат['notes'].append('генерация упала (recaptcha или сервер)')
                break
            if len(txt) > 1200:
                хвост = разбор_ответа(txt, вопрос)
                результат['answer'] = хвост[:8000]
                результат['ok'] = bool(хвост)
                break
        # 2) если не вышло — добываем токен recaptcha и шлём в API сами
        if not результат['ok']:
            ток = await токен_recaptcha(pg)
            результат['notes'].append('recaptcha-токен: %s' % ('получен' if ток else 'не получен'))
            if ток:
                попытка = await pg.evaluate("""async (args) => {
                    try {
                      const r = await fetch('/nextjs-api/stream/create-evaluation', {
                        method:'POST',
                        headers:{'content-type':'application/json','accept':'application/json'},
                        body: JSON.stringify({prompt: args.p, model: args.m, recaptchaToken: args.t})
                      });
                      return {status:r.status, body:(await r.text()).slice(0,400)};
                    } catch(e) { return {status:0, body:String(e).slice(0,150)}; }
                }""", {'p': вопрос, 'm': модель, 't': ток})
                результат['notes'].append('api с токеном: %s %s' % (попытка.get('status'),
                                                                 попытка.get('body', '')[:150]))
        for запись in ошибки[-8:]:
            результат['notes'].append('http %s %s %s' % (запись['status'], запись['url'],
                                                         запись['body'][:120]))
        json.dump(результат, open('solv-%02d.json' % SLOT, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        push('РЕШАТЕЛЬ #%02d | %s\n% s\n\nОТВЕТ:\n%s\n\nЗАМЕТКИ: %s' % (
            SLOT, модель, вопрос[:250], результат['answer'][:1500] or '—',
            '; '.join(результат['notes'])[:400]))
        await pg.screenshot(path='solv-%02d.png' % SLOT)
        await b.close()
        log({'event': 'finish', 'ok': результат['ok'], 'notes': результат['notes']})


asyncio.run(основной())
