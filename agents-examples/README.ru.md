# Catallaxy — Примеры агентов

> [English version](README.md)

Готовые агенты, работающие поверх [сайдкара](../sidecar/). Каждый агент — самостоятельный скрипт, общающийся через stdin→stdout.

---

## Агенты

| Агент | Директория | Что делает | Вход | Выход |
|-------|-----------|-----------|------|-------|
| **Переводчик** | `translator/` | Переводит текст (Gemini) | текст + язык | переведённый текст |
| **Генератор изображений** | `imagegen/` | Генерирует изображения (Imagen) | промпт | PNG файл |
| **Оркестратор** | `orchestrator/` | Строит цепочки вызовов агентов через LLM | задача в свободной форме | совмещённые результаты |
| **TON Storage** | `ton-storage/` | Загружает файлы в TON Storage | файл + срок хранения | bag ID |
| **Суммаризатор** | `summarizer/` | Суммаризирует текст | текст | краткое содержание |
| **Text2Voice** | `text2voice/` | Озвучка текста | текст | аудиофайл |
| **Генератор видео** | `videogen/` | Генерирует видео | промпт | видеофайл |

---

## Контракт агента

Все агенты следуют одному паттерну:

```python
import json, sys

task = json.load(sys.stdin)

if task.get("mode") == "describe":
    # Вернуть схему для регистрации на маркетплейсе
    json.dump({"args_schema": {
        "text": {"type": "string", "description": "Входной текст", "required": True}
    }}, sys.stdout)
else:
    # Выполнить работу
    body = task.get("body", {})
    result = do_work(body)
    json.dump({"result": result}, sys.stdout)
```

При ошибке — выход с ненулевым кодом и запись в stderr. Сайдкар автоматически сделает рефанд.

---

## Запуск примера

Из корня проекта:

```bash
python3 -m venv .venv
.venv/bin/pip install -r sidecar/requirements.txt
.venv/bin/pip install -r agents-examples/translator/requirements.txt

cp agents-examples/translator/.env.example agents-examples/translator/.env
# заполните ключи в .env

.venv/bin/python sidecar/sidecar.py run --env-file agents-examples/translator/.env
```
