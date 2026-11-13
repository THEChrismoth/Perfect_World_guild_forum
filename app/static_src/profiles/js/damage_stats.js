// Поля атаки и пробива переключаются вместе с классом, сохраняя введённые значения.
(function () {
    function init() {
        const selector = document.querySelector('[name="player_class"], [name$="-player_class"]');
        const fields = [...document.querySelectorAll('[data-damage-stat]')];
        if (!selector || !fields.length) return;
        const magicClasses = new Set(fields[0].dataset.magicClasses.split(','));
        const values = new Map(fields.map(field => [field, {
            physical: field.dataset.physicalValue,
            magic: field.dataset.magicValue
        }]));
        function update() {
            const type = magicClasses.has(selector.value) ? 'magic' : 'physical';
            fields.forEach(field => {
                const cached = values.get(field);
                cached[field.dataset.damageType] = field.value;
                if (field.dataset.damageType !== type) field.value = cached[type];
                field.dataset.damageType = type;
                const label = (type === 'magic' ? 'Маг. ' : 'Физ. ') +
                    (field.dataset.damageStat === 'attack' ? 'атака' : 'пробив');
                [...field.labels].forEach(item => { item.textContent = label; });
            });
        }
        selector.addEventListener('change', update);
        update();
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
