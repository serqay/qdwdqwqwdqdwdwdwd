# AI Image Generation Telegram Bot

Многофункциональный Telegram-бот для генерации изображений на базе Stable Diffusion WebUI Forge с интеграцией OmniRoute (LLM), управлением очередями, интерактивным меню, пресетами персонажей и системным треем для мониторинга в Windows.

## Основные возможности

- **Интеграция с SD WebUI Forge**: Асинхронная отправка задач в очередь через headless API (`txt2img`), поддержка моделей NoobAI XL и Illustrious XL с адаптивными весами LoRA.
- **Интерактивный интерфейс Telegram**: Удобные инлайн-клавиатуры для выбора разрешений, стилей, персонажей и параметров генерации.
- **Поддержка поиска тегов**: Быстрый поиск тегов по Danbooru и e621 прямо из интерфейса бота.
- **LLM-интеграция через OmniRoute**: Интеллектуальная оптимизация промптов, генерация описаний и режим ИИ-собеседника.
- **Система очередей и безопасность**: Безопасная перезагрузка (graceful restart) с ожиданием завершения активных генераций, защита от зависаний и мониторинг состояния GPU.
- **Админ-панель**: Управление лимитами пользователей, реферальная система, просмотр статистики и логов.
- **Windows Tray & Service**: Фоновый мониторинг параметров видеокарты (VRAM, температура, нагрузка) в системном трее, скрипты автозапуска и автовосстановления.

## Структура проекта

```text
├── bot/
│   ├── __init__.py
│   ├── ai_character.py   # Логика общения и генерации персонажей через LLM
│   ├── config.py         # Загрузка настроек, пресеты, модели и глобальные блокировки
│   ├── database.py       # Локальная база данных пользователей, лимитов и истории
│   ├── handlers.py       # Обработчики сообщений и колбэков Telegram
│   ├── main.py           # Инициализация и запуск поллинга
│   ├── menus.py          # Генерация инлайн-меню и клавиатур
│   ├── sd_client.py      # Клиент взаимодействия с SD WebUI Forge API
│   ├── search.py         # Поиск тегов в Booru-каталогах
│   ├── telegram_api.py   # Легковесный клиент Telegram Bot API
│   └── worker.py         # Обработчик очереди генерации и graceful shutdown
├── tg_bot_gen.py         # Главная точка входа для запуска бота
├── tray_app.py           # Приложение в системном трее Windows (мониторинг и управление)
├── start_bot_service.ps1 # Скрипт фонового запуска сервиса SD Forge и бота
├── tg_config.example.json# Шаблон файла конфигурации
└── requirements.txt      # Зависимости Python
```

## Установка и запуск

### 1. Требования

- Python 3.10+
- Развернутый Stable Diffusion WebUI Forge (headless или стандартный режим)
- Telegram Bot Token (полученный у [@BotFather](https://t.me/BotFather))

### 2. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 3. Конфигурация

Скопируйте шаблон конфигурации `tg_config.example.json` в `tg_config.json`:

```bash
cp tg_config.example.json tg_config.json
```

Заполните параметры в `tg_config.json`:

```json
{
  "bot_token": "YOUR_TELEGRAM_BOT_TOKEN_HERE",
  "chat_id": "YOUR_TELEGRAM_ADMIN_CHAT_ID",
  "interval_seconds": 120,
  "admin_username": "YOUR_ADMIN_USERNAME",
  "omniroute_key": "YOUR_OMNIROUTE_API_KEY_HERE"
}
```

> **Безопасность:** Файл `tg_config.json` с вашими реальными ключами добавлен в `.gitignore` и не должен попадать в репозиторий.

### 4. Запуск

Запуск бота через консоль:

```bash
python tg_bot_gen.py
```

Запуск приложения в системном трее Windows:

```bash
python tray_app.py
```

Или использование фонового сервиса через PowerShell:

```powershell
.\start_bot_service.ps1
```
