(() => {
    const dialog = document.getElementById('notification-delete-dialog');
    if (!dialog || typeof dialog.showModal !== 'function') return;

    const title = document.getElementById('notification-delete-title');
    const description = document.getElementById('notification-delete-description');
    const remember = document.getElementById('notification-delete-remember');
    const confirmButton = document.getElementById('notification-delete-confirm');
    const preference = dialog.querySelector('.notice-delete-preference');
    const storageKey = `notifications:skip-single-delete:${dialog.dataset.userId}`;
    const approved = new WeakSet();
    let pendingForm = null;

    function skipSingleConfirmation() {
        try { return sessionStorage.getItem(storageKey) === 'yes'; }
        catch (error) { return false; }
    }

    document.addEventListener('submit', (event) => {
        const form = event.target;
        if (!form.matches('form[data-notification-delete]')) return;
        if (approved.has(form)) {
            approved.delete(form);
            return;
        }
        const bulk = form.dataset.notificationDelete === 'all';
        if (!bulk && skipSingleConfirmation()) return;

        event.preventDefault();
        if (dialog.open) return;
        pendingForm = form;
        title.textContent = bulk ? 'Удалить все уведомления?' : 'Удалить уведомление?';
        description.textContent = bulk ? 'Будут удалены все ваши уведомления.' : 'Уведомление будет удалено из вашего списка.';
        confirmButton.textContent = bulk ? 'Удалить все' : 'Удалить';
        preference.hidden = bulk;
        remember.checked = false;
        dialog.showModal();
    });

    confirmButton.addEventListener('click', () => {
        const form = pendingForm;
        if (!form) return;
        if (form.dataset.notificationDelete === 'one' && remember.checked) {
            try { sessionStorage.setItem(storageKey, 'yes'); }
            catch (error) { /* Недоступное хранилище не мешает самому удалению. */ }
        }
        pendingForm = null;
        approved.add(form);
        dialog.close();
        form.requestSubmit();
    });

    dialog.addEventListener('close', () => { pendingForm = null; });
})();
