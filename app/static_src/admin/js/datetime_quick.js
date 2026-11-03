// Быстрые кнопки у поля даты и времени (core/widgets.py DateTimeLocalInput):
// «Сейчас» ставит текущий момент, «+N дн.» — через N дней от поля-основы (например, от даты начала).
(function () {
    function pad(number) {
        return String(number).padStart(2, '0');
    }

    function toLocalValue(date) {
        return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate())
            + 'T' + pad(date.getHours()) + ':' + pad(date.getMinutes());
    }

    document.addEventListener('click', function (event) {
        var button = event.target.closest('[data-datetime-quick]');
        if (!button) return;
        var target = document.getElementById(button.dataset.datetimeTarget);
        var quick = button.dataset.datetimeQuick;
        var date = new Date();
        if (quick !== 'now') {
            var from = button.dataset.datetimeFrom && document.getElementById(button.dataset.datetimeFrom);
            if (from && from.value) date = new Date(from.value);
            var days = parseInt(quick.replace(/[^0-9-]/g, ''), 10) || 0;
            date.setDate(date.getDate() + days);
        }
        target.value = toLocalValue(date);
        target.dispatchEvent(new Event('change', {bubbles: true}));
    });
})();
