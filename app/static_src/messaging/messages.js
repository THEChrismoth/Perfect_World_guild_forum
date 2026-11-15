(() => {
    'use strict';
    const sidebar = document.getElementById('pm-sidebar');
    let sidebarPending = false;
    async function refreshSidebar() {
        if (!sidebar || document.hidden || sidebarPending || sidebar.contains(document.activeElement)) return;
        sidebarPending = true;
        try {
            const url = new URL(document.querySelector('[data-pm-sidebar-url]').dataset.pmSidebarUrl, location.origin);
            url.searchParams.set('partial', '1');
            url.searchParams.set('page', new URLSearchParams(location.search).get('page') || '1');
            const response = await fetch(url, {cache: 'no-store'});
            if (!response.ok || response.redirected) return;
            const data = await response.json();
            const listScroll = sidebar.querySelector('.pm-dialogs')?.scrollTop || 0;
            // HTML строится серверным шаблоном с экранированием пользовательского текста.
            const fragment = new DOMParser().parseFromString(data.sidebar, 'text/html');
            sidebar.replaceChildren(...fragment.body.childNodes);
            sidebar.querySelector('.pm-dialogs').scrollTop = listScroll;
            sidebar.querySelectorAll('.pm-dialog').forEach(link => link.classList.toggle('is-current', new URL(link.href).pathname === location.pathname));
            window.updatePrivateMessageBadge?.(data.unread);
        } catch (_) { /* Список останется доступен при временной потере сети. */ }
        finally { sidebarPending = false; }
    }
    setInterval(refreshSidebar, 15000);
    const thread = document.querySelector('[data-pm-thread]');
    if (!thread || thread.dataset.history === 'yes') return;
    const stream = document.getElementById('pm-stream');
    const form = thread.querySelector('[data-pm-send]');
    const connection = thread.querySelector('.pm-connection');
    const readForm = thread.querySelector('.pm-read-form');
    const csrf = thread.querySelector('[name=csrfmiddlewaretoken]').value;
    let cursor = Number(thread.dataset.lastId), reading = false, polling = false;
    let readCursor = 0;
    if (readForm) readForm.hidden = true;
    const badge = count => window.updatePrivateMessageBadge?.(count);
    const nearBottom = () => stream.scrollHeight - stream.scrollTop - stream.clientHeight < 65;
    async function json(url, options = {}) {
        const response = await fetch(url, {cache: 'no-store', ...options, headers: {'Accept': 'application/json', ...options.headers}});
        if (response.redirected || !response.headers.get('Content-Type')?.includes('application/json')) {
            throw new Error('Соединение прервано. Обновите страницу; перед этим сохраните черновик.');
        }
        const data = await response.json();
        if (!response.ok) throw new Error(data.errors?.join(' ') || 'Не удалось выполнить действие. Попробуйте позже.');
        return data;
    }
    function append(row) {
        if (stream.querySelector(`[data-message-id="${row.id}"]`)) return;
        stream.querySelector('.pm-no-messages')?.remove();
        const bubble = document.createElement('article');
        bubble.className = 'pm-message' + (row.mine ? ' pm-message-mine' : '') + (!row.available ? ' pm-message-unavailable' : '');
        bubble.dataset.messageId = row.id;
        const text = document.createElement('p');
        text.className = 'pm-message-text';
        text.textContent = row.text;
        const footer = document.createElement('footer'), time = document.createElement('time');
        time.dateTime = row.created_at;
        time.textContent = row.time;
        footer.append(time);
        if (row.mine) {
            const receipt = document.createElement('span');
            receipt.className = 'pm-receipt';
            receipt.textContent = row.read ? 'Прочитано' : 'Отправлено';
            footer.append(receipt);
        }
        bubble.append(text, footer);
        // Ответ отправки может прийти раньше предыдущего сообщения из фонового запроса.
        const next = [...stream.querySelectorAll('[data-message-id]')].find(item => Number(item.dataset.messageId) > row.id);
        stream.insertBefore(bubble, next || null);
    }
    async function markRead() {
        if (document.hidden || !nearBottom() || reading || !cursor || readCursor >= cursor) return;
        const upto = cursor;
        reading = true;
        try {
            const data = await json(thread.dataset.readUrl, {method: 'POST', headers: {'X-CSRFToken': csrf}, body: new URLSearchParams({up_to: upto})});
            readCursor = upto;
            badge(data.unread);
        } catch (_) { /* Повторяем подтверждение при следующем обновлении. */ }
        finally { reading = false; }
    }
    async function poll() {
        if (document.hidden || polling) return;
        polling = true;
        try {
            let more;
            do {
                const data = await json(thread.dataset.updatesUrl + '?after=' + cursor);
                const follow = nearBottom();
                for (const row of data.messages) { append(row); cursor = Math.max(cursor, row.id); }
                stream.querySelectorAll('.pm-message-mine').forEach(item => {
                    if (Number(item.dataset.messageId) <= data.read_id) item.querySelector('.pm-receipt').textContent = 'Прочитано';
                });
                if (follow) stream.scrollTop = stream.scrollHeight;
                if (form) form.querySelector('button[type=submit]').disabled = !data.can_send;
                connection.textContent = data.can_send ? '' : 'Отправка сообщений в этот диалог недоступна.';
                badge(data.unread);
                more = data.more;
            } while (more && !document.hidden);
            await markRead();
        } catch (error) { connection.textContent = error.message || 'Нет соединения. Повторим попытку автоматически.'; }
        finally { polling = false; }
    }
    if (form) form.addEventListener('submit', async event => {
        event.preventDefault();
        const button = form.querySelector('button[type=submit]');
        if (button.disabled) return;
        button.disabled = true;
        const body = form.elements.body, submitted = body.value;
        const errors = form.querySelector('.pm-errors');
        errors.textContent = '';
        try {
            const data = await json(form.action, {method: 'POST', body: new FormData(form)});
            append(data.message);
            // Курсор обновлений меняет только poll: нельзя пропустить встречное сообщение.
            if (body.value === submitted) body.value = '';
            form.elements.client_id.value = data.client_id;
            stream.scrollTop = stream.scrollHeight;
            await poll();
        } catch (error) { errors.textContent = error.message || 'Не удалось отправить. Черновик сохранён в поле.'; }
        finally { button.disabled = false; }
    });
    stream.scrollTop = stream.scrollHeight;
    stream.addEventListener('scroll', markRead, {passive: true});
    document.addEventListener('visibilitychange', poll);
    window.addEventListener('focus', poll);
    setInterval(poll, 5000);
    poll();
})();
