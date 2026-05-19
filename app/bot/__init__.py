"""
Telegram-бот: панель управления FunPayWizard.

Основные модули:
  client            — класс TGBot, регистрация хэндлеров
  callbacks         — идентификаторы inline-кнопок и состояний диалога
  keyboards           — динамические клавиатуры
  keyboards_presets   — готовые клавиатуры (меню, отмена, назад)
  helpers             — утилиты бота (уведомления, профиль, навигация)
  onboarding          — первичная настройка в Telegram
  menu_auto_response  — раздел «Автоответ»
  menu_auto_delivery  — раздел «Автовыдача»
  menu_config_files   — загрузка/выгрузка конфигов
  menu_templates      — заготовки ответов
  file_uploads        — загрузка файлов и изображений
  menu_config         — лимиты пагинации в списках
"""
