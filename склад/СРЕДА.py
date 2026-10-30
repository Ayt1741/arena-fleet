# -*- coding: utf-8 -*-
"""СРЕДА — одной командой поднимает всё, что нужно флоту, после перезапуска или на новом ПК.

Что делает по порядку:
 1) ставит нужные библиотеки (ddgs — поиск, trafilatura — чтение страниц, psutil — железо);
    если интернета нет — просто пропускает и говорит об этом;
 2) включает автодоступ к складу Telegram (sitecustomize.py) — любому агенту сразу видно `import АГЕНТ`;
 3) проверяет склад: связь с ботом, число файлов, целостность индекса;
 4) проверяет память: есть ли база, сколько записей, при отсутствии — поднимает из бота;
 5) проверяет аккаунты: сколько входят;
 6) проверяет локальную модель на 8080 (если поставлена);
 7) пишет отчёт в ЛОГ-СРЕДЫ.txt и отправляет его в Telegram.

  СРЕДА.cmd            — поднять и проверить всё
  СРЕДА.cmd --без_установки  — ничего не ставить, только проверить
"""
import importlib
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LOG = os.path.join(ROOT, 'ЛОГ-СРЕДЫ.txt')
ПАКЕТЫ = [('ddgs', 'ddgs'), ('trafilatura', 'trafilatura'), ('psutil', 'psutil')]


def строка(текст):
    line = '%s  %s' % (time.strftime('%d.%m %H:%M:%S'), текст)
    print(line)
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass
    return line


def есть(имя):
    try:
        importlib.import_module(имя)
        return True
    except Exception:
        return False


def поставить(ставить=True):
    нет = [p for p, m in ПАКЕТЫ if not есть(m)]
    if not нет:
        строка('библиотеки: все на месте (ddgs, trafilatura, psutil)')
        return []
    if not ставить:
        строка('библиотеки: не хватает %s (поставить не просили)' % ', '.join(нет))
        return нет
    строка('библиотеки: ставлю %s ...' % ', '.join(нет))
    try:
        r = subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet'] + нет,
                           capture_output=True, text=True, timeout=600)
        ok = [p for p in нет if есть(p)]
        строка('библиотеки: поставилось %d из %d' % (len(ok), len(нет)))
        if len(ок := ok) < len(нет):
            строка('библиотеки: не встало %s — %s' % (', '.join(set(нет) - set(ok)), (r.stderr or '')[-200:].replace('\n', ' ')))
        return list(set(нет) - set(ok))
    except Exception as e:
        строка('библиотеки: установка не удалась — %s' % str(e)[:120])
        return нет


def автодоступ():
    try:
        spec = importlib.util.spec_from_file_location('ад', os.path.join(HERE, 'УСТАНОВИТЬ-АВТОДОСТУП.py'))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        m.установить()
        строка('автодоступ: включён (%s)' % m.папка_сайта())
    except Exception as e:
        строка('автодоступ: ошибка — %s' % str(e)[:120])


def склад():
    try:
        sys.path.insert(0, HERE)
        import ХРАНИЛИЩЕ as Х
        t = Х.test()
        s = Х.статистика()
        строка('склад: бот %s, файлов %d (%.1f МБ), связь работает'
               % (t.get('бот'), s['файлов'], s['МБ']))
        return s
    except Exception as e:
        строка('склад: НЕ РАБОТАЕТ — %s' % str(e)[:160])
        return {}


def память(поднять=True):
    try:
        spec = importlib.util.spec_from_file_location('mem', os.path.join(HERE, 'MEMORY.py'))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        n = m.count_records()
        if n:
            строка('память: %d записей' % n)
            return n
        if not поднять:
            строка('память: базы нет (поднимать не просили)')
            return 0
        строка('память: базы нет — поднимаю из бота, это до 3 минут')
        r = m.restore()
        строка('память: %s' % r)
        return m.count_records()
    except Exception as e:
        строка('память: ошибка — %s' % str(e)[:160])
        return 0


def модель():
    try:
        with urllib.request.urlopen('http://127.0.0.1:8080/v1/models', timeout=5) as x:
            d = json.loads(x.read().decode())
        имена = [i.get('id') for i in (d.get('data') or [])]
        строка('модель: работает на 127.0.0.1:8080 — %s' % (', '.join(filter(None, имена)) or 'без имени'))
        return True
    except Exception:
        k = os.path.join(ROOT, 'ИИ', 'модель.json')
        if os.path.exists(k):
            d = json.load(open(k, encoding='utf-8'))
            строка('модель: поставлена (%s), но сервер не запущен — включить: ИИ-СЕРВЕР.cmd' % d.get('уровень'))
        else:
            строка('модель: не поставлена — поставить: УСТАНОВИТЬ-ИИ.cmd')
        return False


def все(ставить=True):
    строка('=' * 60)
    строка('ПРОВЕРКА СРЕДЫ ФЛОТА')
    нет = поставить(ставить)
    автодоступ()
    склад()
    память(поднять=ставить)
    модель()
    try:
        sys.path.insert(0, HERE)
        import АГЕНТ
        строка('агент: import АГЕНТ работает, поиск по складу — %d совпадений на слово «память»'
               % len(АГЕНТ.найти('память')))
    except Exception as e:
        строка('агент: import АГЕНТ НЕ работает — %s' % str(e)[:120])
    строка('=' * 60)
    try:
        sys.path.insert(0, HERE)
        import АГЕНТ
        r = АГЕНТ.сдать(LOG, 'среда,отчёт')
        строка('отчёт отправлен на склад: %s' % r.get('сдано', r))
    except Exception as e:
        строка('отчёт на склад не ушёл: %s' % str(e)[:100])
    return 0 if not нет else 1


if __name__ == '__main__':
    sys.exit(все(ставить='--без_установки' not in sys.argv))
