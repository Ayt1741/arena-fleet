#!/usr/bin/env python3
"""Вход в Arena через Google на РЕАЛЬНОЙ машине, в реальном (не headless) браузере.
Запускается под Xvfb: экран есть, браузер обычный. Каждый шаг — скриншот в Telegram."""
import json
import os
import re
import sys
import time
import urllib.request
import zipfile

TG_TOKEN = os.environ.get('TG_TOKEN', '')
TG_CHAT = os.environ.get('TG_CHAT', '7023156818')
PAIR = os.environ.get('GOOGLE_ACC', '')
SHOTS = 'shots'
os.makedirs(SHOTS, exist_ok=True)


def tg_send_photo(path, caption=''):
    try:
        b = '----x%d' % int(time.time() * 1000)
        body = []
        body.append(('--%s\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n%s\r\n' % (b, TG_CHAT)).encode())
        body.append(('--%s\r\nContent-Disposition: form-data; name="caption"\r\n\r\n%s\r\n' % (b, caption[:900])).encode())
        body.append(('--%s\r\nContent-Disposition: form-data; name="photo"; filename="%s"\r\nContent-Type: image/png\r\n\r\n'
                     % (b, os.path.basename(path))).encode())
        body.append(open(path, 'rb').read())
        body.append(b'\r\n')
        body.append(('--%s--\r\n' % b).encode())
        r = urllib.request.Request('https://api.telegram.org/bot%s/sendPhoto' % TG_TOKEN, data=b''.join(body), method='POST')
        r.add_header('Content-Type', 'multipart/form-data; boundary=%s' % b)
        urllib.request.urlopen(r, timeout=120).read()
    except Exception as e:
        print('фото не ушло:', str(e)[:80])


def tg_send_text(t):
    try:
        r = urllib.request.Request('https://api.telegram.org/bot%s/sendMessage' % TG_TOKEN,
                                   data=json.dumps({'chat_id': TG_CHAT, 'text': t[:3900]}).encode(), method='POST')
        r.add_header('Content-Type', 'application/json')
        urllib.request.urlopen(r, timeout=60).read()
    except Exception as e:
        print('текст не ушёл:', str(e)[:80])


def shot(pg, name, caption=''):
    p = os.path.join(SHOTS, name + '.png')
    try:
        pg.screenshot(path=p)
        tg_send_photo(p, caption or name)
    except Exception as e:
        print('скрин не снялся:', str(e)[:60])


def main():
    from playwright.sync_api import sync_playwright
    email, _, pwd = PAIR.partition(':')
    if not email or not pwd:
        tg_send_text('GOOGLE_ACC не задан')
        return
    with sync_playwright() as p:
        b = p.chromium.launch(headless=False, args=[
            '--no-sandbox', '--disable-blink-features=AutomationControlled',
            '--start-maximized', '--window-size=1400,900', '--lang=ru-RU'])
        ctx = b.new_context(viewport={'width': 1400, 'height': 900}, locale='ru-RU',
                            timezone_id='Asia/Novosibirsk',
                            user_agent=('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                                        '(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'))
        ctx.add_init_script("""
            Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
            window.chrome={runtime:{}};
            Object.defineProperty(navigator,'languages',{get:()=>['ru-RU','ru','en-US','en']});
            Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});
        """)
        pg = ctx.new_page()
        tg_send_text('Начал вход через Google на реальной машине: %s' % email)
        pg.goto('https://arena.ai/', wait_until='domcontentloaded', timeout=120000)
        pg.wait_for_timeout(9000)
        shot(pg, '01_home', 'Arena открыт')
        # кнопка входа
        clicked = False
        for i in range(12):
            r = pg.evaluate("""() => {
                const els=[...document.querySelectorAll('button,a,[role=button],div')];
                const t=els.filter(e=>/^(log ?in|sign ?in|войти)$/i.test((e.innerText||'').trim()));
                if(!t.length) return '';
                t[t.length-1].click(); return (t[t.length-1].innerText||'').trim();
            }""")
            if r:
                clicked = True
                print('нажал вход:', r)
                break
            pg.wait_for_timeout(2000)
        shot(pg, '02_after_login_click', 'окно входа (нажал: %s)' % ('да' if clicked else 'НЕ нашёл кнопку входа'))
        pg.wait_for_timeout(6000)
        # кнопка Google
        g = pg.evaluate("""() => {
            const els=[...document.querySelectorAll('button,a,[role=button],div,iframe')];
            const t=els.filter(e=>/google/i.test(e.innerText||'')||/google/i.test(e.getAttribute('aria-label')||''));
            if(!t.length) return '';
            t[0].click(); return 'нажал';
        }""")
        print('google:', g)
        pg.wait_for_timeout(12000)
        shot(pg, '03_google_page', 'страница Google: %s' % pg.url)
        tg_send_text('URL: %s\nТекст: %s' % (pg.url, (pg.inner_text('body') or '')[:400].replace('\n', ' | ')))
        # почта
        el = pg.query_selector('input[type=email]')
        if el:
            el.fill(email)
            shot(pg, '04_email', 'почта введена')
            for sel in ['#identifierNext', "button:has-text('Next')", "button:has-text('Далее')"]:
                e2 = pg.query_selector(sel)
                if e2:
                    e2.click()
                    break
            pg.wait_for_timeout(8000)
            shot(pg, '05_after_email', 'после почты')
            pw = pg.query_selector('input[type=password]')
            if pw:
                pw.fill(pwd)
                shot(pg, '06_password', 'пароль введён')
                for sel in ['#passwordNext', "button:has-text('Next')", "button:has-text('Далее')"]:
                    e2 = pg.query_selector(sel)
                    if e2:
                        e2.click()
                        break
                pg.wait_for_timeout(15000)
                shot(pg, '07_after_password', 'после пароля')
            else:
                shot(pg, '06_no_password_field', 'поля пароля нет')
        else:
            shot(pg, '04_no_email_field', 'поля почты нет')
        # итог
        try:
            res = pg.evaluate("""async()=>{try{const r=await fetch('/api/me',{headers:{accept:'application/json'}});
                const j=await r.json(); return r.status+' '+(j.user&&j.user.email||'')}catch(e){return 'err'}}""")
        except Exception as e:
            res = 'err ' + str(e)[:50]
        print('/api/me:', res)
        pg.wait_for_timeout(4000)
        shot(pg, '08_final', 'итог: ' + res)
        tg_send_text('ИТОГ входа через Google\n/api/me: %s\nURL: %s' % (res, pg.url))
        state = '/tmp/google_state.json'
        try:
            ctx.storage_state(path=state)
            with zipfile.ZipFile('/tmp/login-shots.zip', 'w', zipfile.ZIP_DEFLATED) as z:
                for f in os.listdir(SHOTS):
                    z.write(os.path.join(SHOTS, f), f)
                for f in (state,):
                    if os.path.exists(f):
                        z.write(f, os.path.basename(f))
            tg_send_text('Скриншоты собраны: /tmp/login-shots.zip')
        except Exception as e:
            print('состояние не сохранилось:', str(e)[:80])
        b.close()


if __name__ == '__main__':
    main()
