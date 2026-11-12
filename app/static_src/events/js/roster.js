// Фильтр скрывает строки, не сбрасывая выбранных участников.
const playerSearch = document.querySelector('[data-player-search]');
if (playerSearch) {
    playerSearch.addEventListener('input', () => {
        const query = playerSearch.value.trim().toLocaleLowerCase('ru-RU');
        document.querySelectorAll('[data-player-option]').forEach(option => {
            option.hidden = !option.textContent.toLocaleLowerCase('ru-RU').includes(query);
        });
    });
}
