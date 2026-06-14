# Деплой Чатограда на Railway

Это версия проекта, подготовленная под Railway: Dockerfile, `railway.json`, PostgreSQL, healthcheck и переменные окружения уже настроены.

## 1. Подготовь бота в BotFather

В BotFather создай бота или возьми существующего.

Нужны:

- `BOT_TOKEN` — токен бота.
- username бота, например `ChatogradGameBot`.

Желательно отключить Privacy Mode, чтобы бот видел сообщения в группе и мог автоматически добавлять активных участников в город:

```text
/mybots -> твой бот -> Bot Settings -> Group Privacy -> Turn off
```

## 2. Залей проект на GitHub

В папке проекта:

```bash
git init
git add .
git commit -m "Deploy Chatograd to Railway"
```

Создай репозиторий на GitHub и отправь проект:

```bash
git remote add origin https://github.com/USERNAME/REPO.git
git branch -M main
git push -u origin main
```

## 3. Создай проект в Railway

1. Открой Railway.
2. New Project.
3. Deploy from GitHub repo.
4. Выбери репозиторий с ботом.
5. Railway увидит `Dockerfile` и `railway.json`.

## 4. Добавь PostgreSQL

В Railway внутри проекта:

1. Add service.
2. Database.
3. PostgreSQL.

После этого Railway создаст переменную подключения к базе.

## 5. Переменные окружения

В сервисе бота открой **Variables** и добавь:

```env
BOT_TOKEN=твой_токен_от_BotFather
DATABASE_URL=${{Postgres.DATABASE_URL}}
RUN_BOT_POLLING=true
ENABLE_AUTO_EVENTS=true
AUTO_EVENT_INTERVAL_MINUTES=30
AUTO_EVENT_MIN_POPULATION=1
ADMIN_IDS=123456789
APP_SECRET=любой_длинный_секрет_32_символа_или_больше
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
DB_POOL_RECYCLE_SECONDS=1800
AI_ENABLED=false
AI_PROVIDER=openrouter
AI_MODEL=
AI_DAILY_LIMIT_PER_CHAT=3
```

`PORT` руками не добавляй. Railway сам выдаёт порт, а приложение его подхватывает.

Если Railway показывает PostgreSQL сервис не как `Postgres`, выбери переменную через кнопку **Reference variable** и подставь именно `DATABASE_URL` от твоего PostgreSQL-сервиса.

## 6. Деплой

После добавления переменных нажми redeploy.

В логах должно быть примерно так:

```text
Database initialized
Telegram polling task started
Application startup complete
```

Healthcheck:

```text
/api/health
```

Проверка базы:

```text
/api/ready
```

## 7. В Telegram

1. Напиши боту `/start` в личке.
2. Добавь бота в группу.
3. Выдай боту права администратора, желательно с правом удалять сообщения.
4. В группе напиши `/start` или `/menu`.
5. Владелец группы нажимает **👑 Основатель**.

Для удаления старых кнопочных сообщений боту нужны права на удаление сообщений. Без этого игра работает, но старые панели могут оставаться.

## 8. Важные настройки Railway

Рекомендация для первой версии:

- Replicas: `1`.
- Не запускай этот же бот одновременно локально и на Railway.

Telegram long polling не любит, когда один и тот же бот запущен в двух местах сразу. Если включить одновременно локальный запуск и Railway, будут конфликты получения обновлений. Да, бот тоже не любит раздвоение личности.

## 9. Если бот не отвечает

Проверь:

1. `BOT_TOKEN` точно правильный.
2. `RUN_BOT_POLLING=true`.
3. В Railway только одна реплика.
4. Локальная копия бота выключена.
5. В логах нет ошибки подключения к PostgreSQL.
6. Бот добавлен в группу.
7. Privacy Mode выключен, если хочешь авто-добавление активных участников по сообщениям.

## 10. Если база не подключается

Проверь `DATABASE_URL`.

Подходят оба варианта:

```env
postgres://user:password@host:5432/dbname
postgresql://user:password@host:5432/dbname
```

Проект сам преобразует их в формат драйвера `psycopg`.

## 11. Команды для BotFather

```text
start - запустить Чатоград
menu - панель города
city - статус города
founder - основатель района
profile - профиль игрока
daily - ежедневная награда
shop - магазин города
season - сезон города
work - работать
quest - квест дня
gazeta - газета Чатограда
event - событие
drama - драма дня
election - выборы мэра
vote - проголосовать
resolve - завершить событие
top - рейтинг
raid - вызвать город на рейд
raids - входящие рейды
ally - заключить союз
alliances - союзы города
globaltop - глобальный топ городов
officials - должности города
weekly - итоги недели
admin_stats - статистика проекта, только ADMIN_IDS
help - помощь
```
