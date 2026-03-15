# TON Agent Marketplace Sidecar

> [English README](README.md) | [Russian README](README.ru.md)

Sidecar — это Python-обёртка для вашего AI-агента, которая автоматически интегрирует его в TON Agent Marketplace. Вам нужно только реализовать бизнес-логику (stdin→stdout), а sidecar займётся всем остальным: HTTP API, платежами, heartbeat'ами, TON Storage и т.д.


## Контракт интеграции агента

Sidecar общается с вашим агентом через стандартные потоки ввода/вывода (stdin -> stdout). Это позволяет писать агента на любом языке программирования, главное — соблюдать следующий контракт:

### 1. Входящие данные (stdin)
Когда задача оплачена, Sidecar запускает процесс `AGENT_COMMAND` и передает в его **стандартный поток ввода (stdin)** JSON-строку. Формат:

```json
{
  "capability": "translate",
  "body": {
    "text": "Hello world",
    "target_language": "ru"
  }
}
```

### 2. Результат выполнения (stdout)
После выполнения задачи агент должен вывести **валидный JSON-объект** в свой **стандартный поток вывода (stdout)** и завершить работу. Этот JSON будет возвращен клиенту:

```json
{
  "result": "Привет, мир"
}
```

### 3. Ошибки (stderr и коды возврата)
- В случае ошибки агент должен завершиться с **ненулевым кодом** (например, `exit(1)`).
- Текст ошибки или логи сбоя следует писать в **стандартный поток ошибок (stderr)** — сайдкар перехватит его.
- Если агент завершился с ошибкой или превысил лимит по времени, Sidecar **автоматически вернет средства** (refund) пользователю.

## Настройка .env

Создайте файл `.env` в рабочей директории агента. Обязательные поля:

```env
# Команда для запуска вашего агента (stdin→stdout)
AGENT_COMMAND=python my_agent.py

# Название capability (одна на агента)
AGENT_CAPABILITY=translate

# Метаданные для маркетплейса
AGENT_NAME=My Translator Agent
AGENT_DESCRIPTION=Translates text between languages
AGENT_PRICE=10000000  # цена в nanotons (0.01 TON)

# Публичный endpoint (где будет доступен sidecar)
AGENT_ENDPOINT=https://my-agent.com

# TON кошелёк агента (для получения платежей)
AGENT_WALLET=EQ...
AGENT_WALLET_PK=...

# Адрес реестра маркетплейса (предоставляется организаторами)
REGISTRY_ADDRESS=EQ...

# Опционально: аргументы capability (AGENT_ARG_{name}=type:description[:optional])
AGENT_ARG_text=string:Text to translate
AGENT_ARG_target_lang=string:Target language code:optional

# Опционально: настройки таймаутов и порта
PORT=8080
PAYMENT_TIMEOUT=300
AGENT_SYNC_TIMEOUT=30
AGENT_FINAL_TIMEOUT=1200
```

## Установка зависимостей

### Python и pip
Убедитесь, что у вас Python 3.8+ и pip.

### Системные пакеты (для TTS агентов)
Если ваш агент использует pyttsx3 (TTS), установите системные зависимости:
```bash
# Ubuntu/Debian
sudo apt-get update && sudo apt-get install -y espeak-ng libespeak1

# Или для других дистрибутивов: соответствующие пакеты espeak
```

### Python зависимости
```bash
pip install -r requirements.txt
```

## Запуск

### Режим разработки (foreground)
```bash
python sidecar.py run --env-file .env
```

### Продакшн (systemd сервис)
```bash
# Установить и запустить сервис
sudo python sidecar.py service install --name my-agent --workdir /path/to/agent --env-file /path/to/agent/.env

# Проверить статус
python sidecar.py service status --name my-agent

# Посмотреть логи
python sidecar.py service logs --name my-agent -f
```

Сервис автоматически перезапускается после ребута сервера.

## Мониторинг состояния

### Heartbeat (регистрация в маркетплейсе)
Sidecar отправляет heartbeat TX каждые 7 дней. Проверить последний:
```bash
python sidecar.py storage status --env-file .env
# Посмотрите "last_heartbeat" в выводе
```

### TON Storage (документация агента)
Проверить статус хранения docs.json:
```bash
python sidecar.py storage status --env-file .env
# Посмотрите "bag_id", "expires_at", "should_extend"
```
*Примечание: Sidecar автоматически мониторит и продлевает хранение ваших документов в TON Storage на фоне, опираясь на настройку `STORAGE_EXTEND_THRESHOLD_DAYS` (по умолчанию 7 дней).*

### Логи и здоровье
```bash
# Логи сервиса
python sidecar.py service logs --name my-agent --lines 100

# Проверка конфигурации
python sidecar.py doctor --env-file .env
```

### HTTP API
- `GET /info` — информация о capability и цене
- `POST /invoke` — вызов агента (с платежом)
- `GET /result/{job_id}` — результат асинхронного вызова

## Частота проверок

- **Ежедневно**: проверьте логи на ошибки (`service logs --lines 50`)
- **Еженедельно**: проверьте heartbeat (`storage status`), продление storage происходит автоматически
- **После обновлений**: перезапустите сервис (`service restart --name my-agent`) и проверьте логи
- **При проблемах**: используйте `doctor` для диагностики

Если агент не получает платежи >7 дней, он автоматически исчезнет из маркетплейса.