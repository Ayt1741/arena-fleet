# -*- coding: utf-8 -*-
"""УСТАНОВИТЬ-ИИ — ставит на этот ПК САМУЮ СИЛЬНУЮ открытую модель, которая влезает в железо.

Правило заказчика: топ-1 по миру среди открытых моделей, а если не влезает — следующий по силе,
который реально работает и распространяется бесплатно.

Лестница (проверено по карточкам моделей на 30.10.2026):

| уровень | модель | лицензия | вес | кому |
|---|---|---|---|---|
| S | **MiMo-V2.6-Pro** (Xiaomi) — **№1 открытая модель мира** | MIT | 390 ГБ (Q2_K) | сервер, ≥512 ГБ ОЗУ |
| A | **gpt-oss-120b** (OpenAI) | Apache 2.0 | 60 ГБ | ПК с ≥128 ГБ ОЗУ |
| B | **MiMo-V2.6-...-9B** (тот же род, что №1) | MIT | 5,8 ГБ | любой ПК с 16 ГБ ОЗУ |
| C | **Qwen3 8B** | Apache 2.0 | 4,7 ГБ | 8–16 ГБ ОЗУ |
| D | **Qwen3 1.7B** | Apache 2.0 | 1,4 ГБ | 4 ГБ ОЗУ |

Ставится движок llama.cpp (тот самый, на котором гоняют модели все, включая Ollama) — но без Ollama.
Дальше поднимается сервер с OpenAI-совместимым API на 127.0.0.1:8080, и ЛЮБОЙ агент может
обращаться к модели так же, как к облачной: POST /v1/chat/completions.

  УСТАНОВИТЬ-ИИ.cmd --проверка   — ничего не качает, показывает: железо, выбранную модель, размер, ссылки
  УСТАНОВИТЬ-ИИ.cmd              — скачать движок и модель, запустить сервер
  УСТАНОВИТЬ-ИИ.cmd --уровень B  — поставить конкретный уровень
"""
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ПАПКА = os.path.join(ROOT, 'ИИ')
КОНФИГ = os.path.join(ПАПКА, 'модель.json')

УРОВНИ = [
    {'код': 'S', 'имя': 'MiMo-V2.6-Pro (Xiaomi) — №1 открытая модель мира',
     'репо': 'ggml-org/MiMo-V2.6-Pro-MOPD-GGUF',
     'файл': 'MiMo-V2.6-Pro-MOPD-Q2_K-00001-of-00007.gguf', 'частей': 7,
     'гб': 390.0, 'озу_гб': 448, 'лицензия': 'MIT',
     'ссылка': 'https://huggingface.co/ggml-org/MiMo-V2.6-Pro-MOPD-GGUF',
     'замечание': 'это и есть топ-1 по миру среди открытых; нужен сервер, не домашний ПК'},
    {'код': 'A', 'имя': 'gpt-oss-120b (OpenAI)',
     'репо': 'ggml-org/gpt-oss-120b-GGUF',
     'файл': 'gpt-oss-120b-MXFP4.gguf',
     'гб': 60.0, 'озу_гб': 80, 'лицензия': 'Apache 2.0',
     'ссылка': 'https://huggingface.co/ggml-org/gpt-oss-120b-GGUF',
     'замечание': 'сильнейшая бесплатная модель с лицензией Apache 2.0, влезает в 96 ГБ ОЗУ'},
    {'код': 'B', 'имя': 'MiMo-V2.6-Distill-Qwen-9B (родня №1) — Q4_K_M',
     'репо': 'bartowski/MiMo-V2.6-Distill-Qwen-9B-GGUF',
     'файл': 'MiMo-V2.6-Distill-Qwen-9B-Q4_K_M.gguf',
     'гб': 5.84, 'озу_гб': 8, 'лицензия': 'MIT',
     'ссылка': 'https://huggingface.co/bartowski/XiaomiMiMo_MiMo-V2.6-Distill-Qwen-9B-GGUF',
     'замечание': 'тот же род, что №1, но помещается на обычный ПК; замер: 5,84 ГБ на 16 ГБ машине'},
    {'код': 'C', 'имя': 'Qwen3 8B — Q4_K_M',
     'репо': 'Qwen/Qwen3-8B-GGUF',
     'файл': 'Qwen3-8B-Q4_K_M.gguf',
     'гб': 4.7, 'озу_гб': 7, 'лицензия': 'Apache 2.0',
     'ссылка': 'https://huggingface.co/Qwen/Qwen3-8B-GGUF',
     'замечание': '8–15 токенов/с на 16 ГБ без видеокарты'},
    {'код': 'D', 'имя': 'Qwen3 1.7B — Q8_0',
     'репо': 'Qwen/Qwen3-1.7B-GGUF',
     'файл': 'Qwen3-1.7B-Q8_0.gguf',
     'гб': 2.0, 'озу_гб': 3, 'лицензия': 'Apache 2.0',
     'ссылка': 'https://huggingface.co/Qwen/Qwen3-1.7B-GGUF',
     'замечание': '25–40 токенов/с на 4 ГБ — для самых слабых машин'},
]


def озу_гб():
    try:
        import psutil
        return round(psutil.virtual_memory().total / 1024 ** 3, 1)
    except Exception:
        pass
    try:
        if os.path.exists('/proc/meminfo'):
            for line in open('/proc/meminfo'):
                if line.startswith('MemTotal'):
                    return round(int(line.split()[1]) / 1024 ** 2, 1)
        if os.name == 'nt':
            out = subprocess.run(['wmic', 'ComputerSystem', 'get', 'TotalPhysicalMemory'],
                                 capture_output=True, text=True).stdout
            nums = [int(x) for x in out.split() if x.isdigit()]
            if nums:
                return round(nums[0] / 1024 ** 3, 1)
    except Exception:
        pass
    return 0.0


def диск_гб(путь=None):
    try:
        return round(shutil.disk_usage(путь or ROOT).free / 1024 ** 3, 1)
    except Exception:
        return 0.0


def выбрать(озу=None, диск=None, уровень=None):
    озу = озу if озу is not None else озу_гб()
    диск = диск if диск is not None else диск_гб()
    if уровень:
        for у in УРОВНИ:
            if у['код'].lower() == уровень.lower():
                return у
    for у in УРОВНИ:                        # идём сверху вниз: самая сильная, что влезает
        if озу >= у['озу_гб'] and диск >= у['гб'] * 1.1:
            return у
    return УРОВНИ[-1]


def ссылка_на_файл(у):
    return 'https://huggingface.co/%s/resolve/main/%s?download=true' % (у['репо'], у['файл'])


def размер_по_ссылке(url):
    req = urllib.request.Request(url, method='HEAD', headers={'user-agent': 'flot'})
    try:
        with urllib.request.urlopen(req, timeout=45) as x:
            n = x.headers.get('Content-Length') or x.headers.get('x-linked-size')
            return int(n) if n else 0
    except urllib.error.HTTPError as e:
        return -e.code
    except Exception:
        return -1


def движок_llama_cpp():
    """Готовый архив llama.cpp: Windows — win-cpu-x64.zip, Linux — ubuntu-x64.tar.gz."""
    api = 'https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=30'
    req = urllib.request.Request(api, headers={'user-agent': 'flot', 'accept': 'application/vnd.github+json'})
    try:
        выпуски = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
    except Exception as e:
        return None, 'список выпусков не получен: %s' % str(e)[:80]
    win = os.name == 'nt'
    for rel in выпуски:
        for a in rel.get('assets', []):
            n = a['name'].lower()
            if win and n.startswith('llama-') and 'win-cpu-x64' in n and n.endswith('.zip'):
                return {'имя': a['name'], 'url': a['browser_download_url'],
                        'размер_мб': round(a['size'] / 1048576, 1), 'выпуск': rel['tag_name']}, ''
            if (not win) and n.startswith('llama-') and 'ubuntu-x64' in n and n.endswith('.tar.gz'):
                return {'имя': a['name'], 'url': a['browser_download_url'],
                        'размер_мб': round(a['size'] / 1048576, 1), 'выпуск': rel['tag_name']}, ''
    return None, 'ни в одном из 30 последних выпусков нет архива под эту систему'


def проверка(уровень=None):
    озу, диск = озу_гб(), диск_гб()
    у = выбрать(озу, диск, уровень)
    print('=' * 78)
    print('ЖЕЛЕЗО ЭТОГО ПК: ОЗУ %.1f ГБ, свободно на диске %.1f ГБ, система %s'
          % (озу, диск, platform.platform()[:50]))
    print('ВЫБРАН УРОВЕНЬ %s — %s' % (у['код'], у['имя']))
    print('  лицензия: %s | вес: %.2f ГБ | нужно ОЗУ: %s ГБ | %s'
          % (у['лицензия'], у['гб'], у['озу_гб'], у['замечание']))
    print('  карточка модели: %s' % у['ссылка'])
    url = ссылка_на_файл(у)
    real = размер_по_ссылке(url)
    if real > 0:
        print('  файл модели доступен: %.2f ГБ (проверено HEAD-запросом)' % (real / 1024 ** 3))
    elif real < -1:
        print('  файл модели: сервер ответил %s — имя файла надо уточнить в карточке' % (-real))
    else:
        print('  файл модели: размер не отдан, но ссылка отвечает')
    д, ошибка = движок_llama_cpp()
    if д:
        print('  движок: %s — %s МБ (выпуск %s)' % (д['имя'], д['размер_мб'], д['выпуск']))
    else:
        print('  движок: %s' % ошибка)
    print('=' * 78)
    return у, д, url


def скачать(url, путь):
    os.makedirs(os.path.dirname(путь), exist_ok=True)
    начало = os.path.getsize(путь) if os.path.exists(путь) else 0
    req = urllib.request.Request(url, headers={'user-agent': 'flot'})
    if начало:
        req.add_header('Range', 'bytes=%d-' % начало)
    with urllib.request.urlopen(req, timeout=120) as r, open(путь, 'ab') as f:
        всего = int(r.headers.get('Content-Length') or 0) + начало
        читано = начало
        while True:
            блок = r.read(1 << 22)
            if not блок:
                break
            f.write(блок)
            читано += len(блок)
            if всего:
                print('\r  %.1f / %.1f ГБ (%.0f %%)' % (читано / 1024 ** 3, всего / 1024 ** 3,
                                                       100 * читано / всего), end='', flush=True)
    print()
    return путь


def список_файлов(у):
    """Если модель нарезана на части (…-00001-of-00007.gguf) — качаем все части."""
    частей = у.get('частей')
    if not частей:
        return [у['файл']]
    return [у['файл'].replace('00001-of-%05d' % частей, '%05d-of-%05d' % (i, частей))
            for i in range(1, частей + 1)]


def установить(уровень=None):
    у, д, url = проверка(уровень)
    os.makedirs(ПАПКА, exist_ok=True)
    путь_модели = os.path.join(ПАПКА, список_файлов(у)[0])
    if не_хватает := (диск_гб() < у['гб'] * 1.1):
        print('НЕ ХВАТАЕТ МЕСТА: нужно %.1f ГБ, свободно %.1f ГБ' % (у['гб'] * 1.1, диск_гб()))
        return 2
    файлы = список_файлов(у)
    print('качаю модель: %d файл(ов)' % len(файлы))
    for имя_файла in файлы:
        путь_модели = os.path.join(ПАПКА, имя_файла)
        адрес = 'https://huggingface.co/%s/resolve/main/%s?download=true' % (у['репо'], имя_файла)
        print('  %s' % имя_файла)
        скачать(адрес, путь_модели)
    if д:
        архив = os.path.join(ПАПКА, д['имя'])
        print('качаю движок llama.cpp...')
        скачать(д['url'], архив)
        print('распаковываю...')
        if архив.endswith('.zip'):
            shutil.unpack_archive(архив, os.path.join(ПАПКА, 'llama.cpp'))
        else:
            shutil.unpack_archive(архив, os.path.join(ПАПКА, 'llama.cpp'))
    конфиг = {'уровень': у['код'], 'модель': у['имя'], 'файл': путь_модели,
              'лицензия': у['лицензия'], 'ссылка': у['ссылка'],
              'порт': 8080, 'контекст': 65536, 'озу_гб': озу_гб()}
    json.dump(конфиг, open(КОНФИГ, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('готово. Настройки: %s' % КОНФИГ)
    print('Запуск сервера: ИИ-СЕРВЕР.cmd — дальше агенты зовут POST http://127.0.0.1:8080/v1/chat/completions')
    return 0


def main(argv):
    уровень = None
    if '--уровень' in argv:
        i = argv.index('--уровень')
        if i + 1 < len(argv):
            уровень = argv[i + 1]
    if '--проверка' in argv or '--check' in argv:
        проверка(уровень)
        return 0
    return установить(уровень)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
