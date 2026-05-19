# Участие в разработке

Спасибо за интерес к FunPayWizard!

## Как помочь

1. **Issues** — баги и идеи через [шаблоны](.github/ISSUE_TEMPLATE/)
2. **Pull requests** — небольшие, понятные изменения с описанием
3. **Документация** — правки в `docs/` и `README.md`

## Перед PR

```bash
pip install -r requirements.txt
python -m compileall -q api app main.py
```

Не коммить: `.env`, `configs/` с ключами, `storage/cache/` с личными данными.

## Стиль кода

- Следуй существующей структуре (`app/bot/`, `handlers.py`)
- Минимальный diff — без лишнего рефакторинга
- Тексты интерфейса — в `app/constants/texts.py`

## Вопросы

- [Telegram @FunPayWizard](https://t.me/FunPayWizard)
- [Группа поддержки](https://t.me/+Z3Fgq6YXytk1ODEy)
