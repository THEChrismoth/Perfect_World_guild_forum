document.querySelector('[data-copy-skirmish]')?.addEventListener('click', async function () {
    const field = document.getElementById('sk-share-url');
    try {
        await navigator.clipboard.writeText(field.value);
        this.textContent = 'Ссылка скопирована';
    } catch (error) {
        field.focus();
        field.select();
        this.textContent = 'Скопируйте выделенную ссылку';
    }
});
