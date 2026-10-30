# -*- coding: utf-8 -*-
"""АВТОДОСТУП — чтобы КАЖДЫЙ новый агент сразу видел хранилище, без единой строки настройки.

Что делает: кладёт в пользовательскую папку Python файл sitecustomize.py. Python читает его
при запуске ЛЮБОГО скрипта на этой машине — значит в любом новом агенте сразу работают:

    import АГЕНТ
    АГЕНТ.сдать('файл.md')      # залить в Telegram
    АГЕНТ.взять('файл.md')      # достать
    АГЕНТ.найти('слово')        # поиск по всему складу

Ни путей, ни настройки, ни копирования файлов — просто работает.

Запуск: АВТОДОСТУП.cmd   (или python УСТАНОВИТЬ-АВТОДОСТУП.py)
"""
import os
import site
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

ШАБЛОН = '''# -*- coding: utf-8 -*-
# Создано ФЛОТ-флотом: подключает общий склад Telegram к ЛЮБОМУ python-скрипту на этой машине.
# Удалить автодоступ: удалить этот файл или запустить УСТАНОВИТЬ-АВТОДОСТУП.py --удалить
import os as _os
import sys as _sys

ФЛОТ_ПАМЯТЬ = %r
if _os.path.isdir(ФЛОТ_ПАМЯТЬ) and ФЛОТ_ПАМЯТЬ not in _sys.path:
    _sys.path.append(ФЛОТ_ПАМЯТЬ)
'''


def папка_сайта():
    try:
        путь = site.getusersitepackages()
    except Exception:
        путь = os.path.join(os.path.expanduser('~'), '.local', 'lib', 'python3', 'site-packages')
    os.makedirs(путь, exist_ok=True)
    return путь


def установить():
    цель = os.path.join(папка_сайта(), 'sitecustomize.py')
    старый = ''
    if os.path.exists(цель):
        старый = open(цель, encoding='utf-8').read()
        if 'ФЛОТ-флотом' not in старый and 'sitecustomize' in старый:
            print('ВНИМАНИЕ: %s уже есть и создан не нами. Делаю копию и дописываю своё.' % цель)
            open(цель + '.было', 'w', encoding='utf-8').write(старый)
            старый = ''
    свой = ШАБЛОН % HERE
    if 'ФЛОТ_ПАМЯТЬ' in старый:
        свой = старый.split('import os as _os')[0] + свой.split('import os as _os', 1)[1]
    with open(цель, 'w', encoding='utf-8') as f:
        f.write(свой)
    print('Автодоступ установлен: %s' % цель)
    print('Папка склада: %s' % HERE)
    return цель


def удалить():
    цель = os.path.join(папка_сайта(), 'sitecustomize.py')
    if os.path.exists(цель) and 'ФЛОТ-флотом' in open(цель, encoding='utf-8').read():
        os.remove(цель)
        print('Автодоступ удалён: %s' % цель)
    else:
        print('Нашего автодоступа нет — удалять нечего')
    return цели_нет()


def цели_нет():
    return True


def проверить():
    print('--- проверка ---')
    print('папка сайта:', папка_сайта())
    цель = os.path.join(папка_сайта(), 'sitecustomize.py')
    print('файл на месте:', os.path.exists(цель))
    print('папка склада в sys.path:', HERE in sys.path)
    try:
        import АГЕНТ
        print('АГЕНТ подключается:', True)
        print('склад:', АГЕНТ.сколько())
    except Exception as e:
        print('АГЕНТ НЕ подключается:', str(e)[:160])


if __name__ == '__main__':
    if '--удалить' in sys.argv:
        удалить()
    else:
        установить()
        проверить()
