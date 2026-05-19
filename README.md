<h1 align="center">FunPayWizard</h1>

<p align="center">
  Бот для автоматизации продаж на <a href="https://funpay.com">FunPay</a> с полноценной панелью управления в Telegram.
</p>

<p align="center">
  <img src="assets/funpaywizard-preview.png" alt="FunPayWizard" width="640">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.9%2B-blue?style=flat-square" alt="Python">
  <img src="https://img.shields.io/badge/Telegram-бот-26A5E4?style=flat-square" alt="Telegram">
  <a href="https://t.me/FunPayWizard"><img src="https://img.shields.io/badge/чат-@FunPayWizard-26A5E4?style=flat-square" alt="Чат"></a>
  <a href="https://t.me/+cBJMWvCXBkJhMmRi"><img src="https://img.shields.io/badge/поддержка-группа-8B5CF6?style=flat-square" alt="Поддержка"></a>
</p>

<p align="center">
  <a href="docs/quick-start.md">Быстрый старт</a> ·
  <a href="docs/installation.md">Установка</a> ·
  <a href="docs/configuration.md">Конфиги</a> ·
  <a href="docs/telegram.md">Telegram</a> ·
  <a href="docs/group-topics.md">Группа с топиками</a> ·
  <a href="docs/analytics.md">Аналитика</a>
</p>

---

## Возможности

### FunPay

- **Автовыдача** — выдача товаров по заказам, привязка лотов к файлам в `storage/products/`
- **Автоподнятие** лотов по расписанию
- **Автоответ** на команды в чате покупателя
- **Восстановление и отключение** лотов при нехватке товара
- Уведомления о заказах, сообщениях, отзывах, подтверждениях, выдаче и поднятии лотов
- Ответы покупателям и возвраты из Telegram

### Telegram-панель

- Управление через `/menu`, reply-клавиатуру и inline-кнопки
- **Единые уведомления** — одни переключатели для лички и группы; опция **«Все уведомления в группу»**
- **Фильтр переписки** (✉️ Сообщения) — что показывать в уведомлениях; те же правила для топиков
- **Группа с топиками** — топик на каждого покупателя, ответы из Telegram на FunPay; системный топик для отзывов и подтверждений
- **Шаблоны ответов** — в личке и быстрая отправка из топика покупателя
- **Аналитика** — отчёт по балансу, продажам, возвратам, лотам и сводке за сегодня (блоки на выбор)
- **Глубокие настройки** — автоответ, автовыдача, ЧС, приветствие, ответы на заказ и отзывы, конфиги
- Чёрный список, вечерняя сводка (23:00), `/profile` и расширенная статистика

### Для разработчиков

- Python 3.9+, модульная структура (`api/`, `app/`)
- Пакет `api` — клиент FunPay, отдельно от Telegram UI
- Docker, установочный скрипт для Linux, CI на GitHub Actions

## Быстрый старт

```bash
git clone https://github.com/neluckoff/FunPayWizard.git
cd FunPayWizard
pip install -r requirements.txt
cp .env.example .env   # укажи TELEGRAM_BOT_TOKEN от @BotFather
python main.py
```

При первом запуске бот проведёт настройку в Telegram: golden key, пароль администратора, опционально группа с топиками.

Подробнее: [docs/quick-start.md](docs/quick-start.md)

## Установка

| Способ | Документация |
|--------|----------------|
| Windows | [docs/installation.md#windows](docs/installation.md#windows) |
| Linux (скрипт) | [docs/installation.md#linux](docs/installation.md#linux) |
| Docker | [docs/installation.md#docker](docs/installation.md#docker) |

```bash
# Linux — автоматическая установка
wget https://raw.githubusercontent.com/neluckoff/FunPayWizard/main/linux-install.sh -nc && bash linux-install.sh
```

```bash
# Docker
docker compose up -d --build
docker compose logs -f funpay-wizard
```

## Структура проекта

```
api/                 # клиент FunPay API
app/
  bot/               # Telegram: client, keyboards, меню, группа с топиками
  constants/         # тексты интерфейса
  utils/             # конфиги, логгер, хелперы
  assistant.py       # ядро
  handlers.py        # обработчики событий FunPay
assets/              # изображения для бота и README
configs/             # конфигурация (создаётся при настройке)
storage/             # кэш, товары, шаблоны
docs/                # документация
main.py              # точка входа
```

## Конфигурация

| Файл | Назначение |
|------|------------|
| `configs/_main.cfg` | Основные переключатели, Telegram, группа |
| `configs/auto_response.cfg` | Автоответчик |
| `configs/auto_delivery.cfg` | Автовыдача |
| `.env` | Токен бота (`TELEGRAM_BOT_TOKEN`) |

Инструкции внутри конфигов и в [docs/configuration.md](docs/configuration.md).

## Сообщество и поддержка

- Чат: [@FunPayWizard](https://t.me/FunPayWizard)
- Группа поддержки: [перейти](https://t.me/+cBJMWvCXBkJhMmRi)

Баги и предложения — через [Issues](https://github.com/neluckoff/FunPayWizard/issues). Как внести правки: [CONTRIBUTING.md](CONTRIBUTING.md).

## Поддержать проект

- ⭐ Звезда на GitHub
- [GitHub Sponsors / Funding](https://github.com/sponsors/neluckoff)

---

<p align="center">
  <sub>FunPayWizard не аффилирован с FunPay. Используйте на свой страх и риск, соблюдая правила площадки.</sub>
</p>
