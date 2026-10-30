# -*- coding: utf-8 -*-
"""АГЕНТ — три строки, которые подключают любого агента к общему складу и к сторожу.

Любой агент (совет, слежка, флот, бот, скрипт на другом ПК) делает так:

    import АГЕНТ
    АГЕНТ.работаю('совет')            # сказал сторожу: я живой, заморозку не надо
    ...
    АГЕНТ.сдать('/путь/итог.md', 'совет,итоги')   # залил результат в Telegram
    АГЕНТ.взять('итог.md', '/куда/')              # забрал чужой результат из Telegram
    АГЕНТ.что_есть()                              # список всего на складе
    АГЕНТ.найти('память')                         # поиск по складу

Всё бесплатно: склад — это чат в Telegram, место там не кончается.
Работает на Windows и Linux. Если Telegram недоступен, агент не падает:
функции возвращают словарь с ошибкой, работу можно продолжать.
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _модуль(имя_файла, имя_модуля):
    путь = os.path.join(HERE, имя_файла)
    spec = importlib.util.spec_from_file_location(имя_модуля, путь)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_Х = None
_С = None


def _хранилище():
    global _Х
    if _Х is None:
        _Х = _модуль('ХРАНИЛИЩЕ.py', 'хранилище_флот')
    return _Х


def _сторож():
    global _С
    if _С is None:
        try:
            _С = _модуль('СТОРОЖ.py', 'сторож_флот')
        except Exception:
            _С = False
    return _С or None


def работаю(имя='агент'):
    """Отметка активности: сторож не заморозит задачу и не потратит лимит зря."""
    try:
        с = _сторож()
        if с:
            с.отметить(имя)
        return {'отметил': имя}
    except Exception as e:
        return {'ошибка': str(e)[:120]}


def сдать(путь, теги=''):
    """Залить файл (или папку) в общий склад Telegram."""
    try:
        r = _хранилище().положить(путь, теги)
        работаю(теги.split(',')[0] if теги else 'агент')
        return {'сдано': os.path.basename(путь), 'теги': теги, 'склад': r}
    except Exception as e:
        return {'ошибка': str(e)[:160], 'файл': путь}


def взять(имя, куда='.'):
    """Забрать файл со склада (с проверкой sha256)."""
    try:
        return _хранилище().взять(имя, куда)
    except Exception as e:
        return {'ошибка': str(e)[:160], 'файл': имя}


def что_есть():
    try:
        return _хранилище().список()
    except Exception as e:
        return [{'ошибка': str(e)[:160]}]


def найти(текст):
    try:
        return _хранилище().найти(текст)
    except Exception as e:
        return [{'ошибка': str(e)[:160]}]


def сколько():
    try:
        return _хранилище().статистика()
    except Exception as e:
        return {'ошибка': str(e)[:160]}


if __name__ == '__main__':
    print('склад:', сколько())
    for r in что_есть()[:20]:
        print(' ', r)
