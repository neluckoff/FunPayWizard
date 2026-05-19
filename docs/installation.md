# Установка

## Windows

1. Установи [Python 3.10+](https://www.python.org/downloads/). При установке включи **Add python.exe to PATH**.
2. Скачай или клонируй репозиторий:

   ```bash
   git clone https://github.com/neluckoff/FunPayWizard.git
   ```

3. В папке проекта:

   ```cmd
   pip install -r requirements.txt
   copy .env.example .env
   ```

4. Заполни `.env` (токен бота) и запусти `Start.bat` или `python main.py`.
5. Пройди настройку в Telegram (`/start`).

## Linux

### Автоустановка (Ubuntu)

```bash
wget https://raw.githubusercontent.com/neluckoff/FunPayWizard/main/linux-install.sh -nc && bash linux-install.sh
```

Скрипт установит зависимости, клонирует репозиторий и запустит процесс через **pm2** (`FunPayWizard`).

Логи:

```bash
pm2 logs FunPayWizard
```

### Вручную

```bash
git clone https://github.com/neluckoff/FunPayWizard.git
cd FunPayWizard
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

## Docker

Перед Docker имеет смысл один раз пройти настройку локально (появятся `configs/` и `storage/`).

```bash
git clone https://github.com/neluckoff/FunPayWizard.git
cd FunPayWizard
# настрой configs/ и .env при необходимости
docker compose up -d --build
```

Проверка:

```bash
docker compose logs -f funpay-wizard
```

Остановка:

```bash
docker compose down
```

Тома в `docker-compose.yml`: `configs/`, `storage/`, `logs/`.

## Обновление

```bash
cd FunPayWizard
git pull
pip install -r requirements.txt
# перезапусти процесс: Start.bat, pm2 restart FunPayWizard или docker compose up -d --build
```
