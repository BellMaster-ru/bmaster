# bmaster

Система управления интеркомами (преимущественно используемая в школах) с backend на FastAPI и встроенным web-интерфейсом.

![Скриншот интерфейса](./img/img2.png)

## Требования

- Python `3.13+` (см. `pyproject.toml`)
- `pip`
- `git`
- Доступ в интернет для загрузки frontend-билда при установке/обновлении
- ОС: Linux или Windows

## Быстрый старт

### 1. Клонирование

```bash
git clone https://github.com/wumtdev/bmaster.git
cd bmaster
```

### 2. Установка

Linux/macOS:

```bash
chmod +x setup.sh
./setup.sh
```

Windows:

```bat
setup.bat
```

Что делает установка:

- устанавливает `uv` и зависимости проекта;
- создаёт служебные директории и файлы в `data/`;
- генерирует самоподписанный SSL сертификат (`data/cert.pem`, `data/key.pem`), если его нет;
- загружает и распаковывает последний frontend билд в `static/`.

### 3. Запуск

```bash
uv run main.py
```

По умолчанию сервер поднимается на `https://0.0.0.0:8000`.

- API документация (Swagger): `https://<ip адрес сервера>:8000/docs`
- API префикс: `/api`

## Конфигурация

Основной конфиг: `data/config.yml`.

Ключевые значения по умолчанию:

- `server.ssl.enabled: true`
- `auth.service.enabled: true`
- пароль сервисного root-доступа по умолчанию: `rpass`

После первого запуска рекомендуется сменить пароль в `data/config.yml` (`auth.service.password`).

## Обновления

### Через веб-интерфейс

```
WIP
```

### Через скрипты

Проверка обновлений:

```bash
uv run check_updates.py
```

Обновление backend + frontend:

```bash
uv run update.py
```

## Дополнительная информация

Для разработки проекта использовались:

- Python 3.13+
- VS Code
- Навыки в программировании и клавиатура

```
С любовью и терпением разрабатывают и поддерживают проект frum1 и wumtdev.
2025-20xx
```
