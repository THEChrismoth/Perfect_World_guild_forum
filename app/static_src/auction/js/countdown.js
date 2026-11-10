// Обратный отсчёт до конца торгов: [data-countdown="время окончания в мс"] с [data-countdown-text] внутри.
// Больше суток — «2 д 03 ч», меньше — «03:14:05», последние 5 минут подсвечиваются (.is-ending).
// Страница лота меняет data-countdown, когда торги продлили (см. lot_detail.html).
(function () {
    function pad(number) {
        return String(number).padStart(2, '0');
    }

    function format(ms) {
        var total = Math.floor(ms / 1000);
        var days = Math.floor(total / 86400);
        var hours = Math.floor(total % 86400 / 3600);
        var minutes = Math.floor(total % 3600 / 60);
        var seconds = total % 60;
        if (days > 0) return days + ' д ' + pad(hours) + ' ч';
        return pad(hours) + ':' + pad(minutes) + ':' + pad(seconds);
    }

    function tick() {
        var now = Date.now();
        document.querySelectorAll('[data-countdown]').forEach(function (timer) {
            var left = parseInt(timer.dataset.countdown, 10) - now;
            var text = timer.querySelector('[data-countdown-text]') || timer;
            text.textContent = left > 0 ? format(left) : 'итоги подводятся';
            timer.classList.toggle('is-ending', left > 0 && left < 5 * 60 * 1000);
            timer.classList.toggle('is-over', left <= 0);
        });
    }

    tick();
    setInterval(tick, 1000);
})();
