(() => {
    'use strict';
    const link = document.querySelector('[data-pm-badge-url]');
    if (!link) return;
    window.updatePrivateMessageBadge = count => {
        const badge = link.querySelector('[data-pm-badge]');
        badge.textContent = count > 99 ? '99+' : String(count);
        badge.hidden = !count;
        link.setAttribute('aria-label', `Личные сообщения: ${count} непрочитанных`);
        const nav = document.querySelector(`.site-nav-link[href="${link.getAttribute('href')}"]`);
        if (nav) {
            let counter = nav.querySelector('.site-nav-badge');
            if (count && !counter) {
                counter = document.createElement('span');
                counter.className = 'site-nav-badge';
                nav.append(counter);
            }
            if (counter) { counter.textContent = count > 99 ? '99+' : String(count); counter.hidden = !count; }
        }
    };
    let pending = false;
    async function refresh() {
        if (document.hidden || pending) return;
        pending = true;
        try {
            const response = await fetch(link.dataset.pmBadgeUrl, {cache: 'no-store'});
            if (response.ok && !response.redirected) window.updatePrivateMessageBadge((await response.json()).unread);
        } catch (_) { /* При потере сети сохраняем последний известный счётчик. */ }
        finally { pending = false; }
    }
    setInterval(refresh, 30000);
    document.addEventListener('visibilitychange', refresh);
})();
