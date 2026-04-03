# HCS — Hardening & Compliance System

Автоматизированная Enterprise-система для контроля соответствия сетевого оборудования стандартам безопасности (Compliance & Hardening).

## Возможности

- **Мультивендорность:** Cisco (IOS/NX-OS/XR/ASA), Juniper, Arista, Eltex, Huawei, FortiGate, Palo Alto, Check Point, MikroTik, Nokia и др.
- **Универсальный сбор данных:** GitLab/Git, SSH (Netmiko), NETCONF, SNMP, REST API, локальные файлы.
- **Движок проверок:** Regex, иерархические блоки (ciscoconfparse2), TextFSM, JSON/XML/XPath, версионные проверки, композитные правила.
- **Горизонтальное масштабирование:** Celery-воркеры с раздельными очередями (scan/sync/maintenance).
- **Remediation:** Генерация Ansible Playbooks, запуск через AWX/Tower или SSH.
- **Отчётность:** Dashboard, Compliance Matrix, CSV Export, Prometheus metrics.

## Технологический стек

| Компонент | Технология |
|-----------|-----------|
| Backend | Python 3.12, Flask 3.x, SQLAlchemy 2.x |
| Database | PostgreSQL 16 |
| Cache/Broker | Redis 7 |
| Task Queue | Celery 5.x (раздельные очереди scan/sync/maintenance) |
| Frontend | Jinja2, Vanilla JS, CSS |
| Container | Docker, Docker Compose |

## Архитектура

```
┌────────────────────────────────────────────────────────────┐
│                        Nginx (TLS)                         │
│                     hcs.example.com:443                     │
└──────────────────────────┬─────────────────────────────────┘
                           │ proxy_pass :8000
┌──────────────────────────▼─────────────────────────────────┐
│  HCS Web (Gunicorn)              [hcs-web]                 │
│  Flask API + UI                   :8000                    │
├────────────────────────────────────────────────────────────┤
│              │ Celery tasks                                │
│              ▼                                             │
│  ┌─────────────────┐  ┌──────────────┐  ┌───────────────┐ │
│  │ collector-scan   │  │collector-sync│  │  maintenance  │ │
│  │ (масштабируемый) │  │              │  │  + beat       │ │
│  │ -Q scan          │  │ -Q sync      │  │  -Q maint     │ │
│  └────────┬─────────┘  └──────┬───────┘  └───────────────┘ │
│           │                   │                            │
│  ┌────────▼───────────────────▼─────────────────────────┐  │
│  │              Redis (Broker)                          │  │
│  └──────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │         PostgreSQL (Data Store)                      │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

---

## Быстрый старт (Разработка)

### Предварительные требования

- Docker ≥ 24.0 + Docker Compose v2
- Python 3.11+ (для локальной разработки без Docker)

### Вариант 1: Docker Compose (рекомендуется)

```bash
# 1. Клонирование
git clone https://git.example.com/infra/hcs.git
cd hcs

# 2. Настройка окружения
cp .env.example .env
# Отредактировать .env — минимум указать SECRET_KEY

# 3. Сборка и запуск
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# 4. Проверка
curl http://localhost:8000/health
# {"status": "ok"}

# Web UI: http://localhost:8000
```

> При первом запуске `web`-контейнер автоматически выполнит миграции и загрузит начальные данные (вендоры, admin-пользователь).

### Вариант 2: Локально (без Docker)

```bash
# 1. Виртуальное окружение
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Настройка
cp .env.example .env
# Указать DATABASE_URL и REDIS_URL (к внешним PostgreSQL и Redis)

# 3. Инициализация БД
flask db upgrade
flask seed          # Загрузить вендоры и демо-данные
flask seed-admin    # Создать admin пользователя

# 4. Запуск
flask run --host=0.0.0.0 --port=8000

# 5. Celery Worker (в отдельном терминале)
celery -A app.tasks worker -Q scan,sync,maintenance,default -c 4 --loglevel=info

# 6. Celery Beat (в отдельном терминале)
celery -A app.tasks beat --loglevel=info
```

---

## Продакшн-деплой (Docker, Air-Gapped)

Сценарий: сборка на тестовом сервере (есть интернет) → перенос образов на прод (без интернета).

### Шаг 1: Сборка на тестовом сервере

```bash
cd hcs/

# Сборка с версионным тегом
docker build -t hcs:1.0.0 -t hcs:latest .

# Если интернет через прокси:
docker build \
  --build-arg HTTP_PROXY=http://proxy.internal:3128 \
  --build-arg HTTPS_PROXY=http://proxy.internal:3128 \
  -t hcs:1.0.0 -t hcs:latest .

# Скачать зависимые образы
docker pull postgres:16-alpine
docker pull redis:7-alpine
```

### Шаг 2: Экспорт образов

```bash
# Все образы в один архив (~235MB сжатый)
docker save hcs:1.0.0 hcs:latest postgres:16-alpine redis:7-alpine \
  | gzip > hcs-bundle-1.0.0.tar.gz

# Или только HCS (при обновлении, postgres/redis уже на проде)
docker save hcs:1.0.0 hcs:latest | gzip > hcs-app-1.0.0.tar.gz
```

### Шаг 3: Перенос на прод

```bash
# scp, rsync, USB-накопитель — как удобнее
scp hcs-bundle-1.0.0.tar.gz user@prod-server:/opt/hcs/
```

### Шаг 4: Развёртывание на проде

```bash
ssh user@prod-server
cd /opt/hcs

# 1. Загрузить образы
docker load < hcs-bundle-1.0.0.tar.gz

# 2. Подготовить конфигурацию
cp .env.production .env
vi .env
```

**Обязательно заполнить в `.env`:**

```bash
# Сгенерировать ключ:
#   python3 -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=<сгенерированный_ключ>

# Пароль БД (одинаковый в обоих местах)
POSTGRES_PASSWORD=<надёжный_пароль>
DATABASE_URL=postgresql://hcs:<надёжный_пароль>@postgres:5432/hcs
```

```bash
# 3. Запуск
docker compose up -d

# 4. Проверить логи первого запуска (migrate + seed)
docker compose logs -f web

# 5. Проверка
docker compose ps
curl http://localhost:8000/health
```

### Масштабирование

```bash
# 3 параллельных scan-воркера
docker compose up -d --scale collector-scan=3

# Настройки потоков в .env
SCAN_CONCURRENCY=8    # потоков на scan-контейнер
SYNC_CONCURRENCY=2    # потоков на sync-контейнер
GUNICORN_WORKERS=4    # процессов веб-сервера
```

### Обновление

```bash
# На тестовом сервере:
docker build -t hcs:1.1.0 -t hcs:latest .
docker save hcs:1.1.0 hcs:latest | gzip > hcs-app-1.1.0.tar.gz
scp hcs-app-1.1.0.tar.gz user@prod-server:/opt/hcs/

# На проде:
cd /opt/hcs
docker load < hcs-app-1.1.0.tar.gz
docker compose up -d    # entrypoint автоматически запустит миграции

# Откат (при проблемах):
# В .env: HCS_IMAGE=hcs:1.0.0
# docker compose up -d
```

---

## Настройка Nginx

HCS работает на порту 8000. Для продакшна рекомендуется поставить Nginx как reverse proxy с TLS.

### Установка

```bash
# RHEL/CentOS
sudo yum install -y nginx

# Debian/Ubuntu
sudo apt install -y nginx
```

### Конфигурация

Готовый конфиг — [`deploy/nginx/hcs.conf`](deploy/nginx/hcs.conf).

```bash
# 1. Скопировать конфиг
sudo cp deploy/nginx/hcs.conf /etc/nginx/conf.d/hcs.conf

# 2. Заменить server_name
sudo sed -i 's/hcs.example.com/ваш-домен.ru/g' /etc/nginx/conf.d/hcs.conf
```

### SSL сертификат

**Вариант A: Самоподписанный (air-gapped среда)**

```bash
sudo mkdir -p /etc/nginx/ssl

sudo openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout /etc/nginx/ssl/hcs.key \
  -out /etc/nginx/ssl/hcs.crt \
  -subj "/CN=ваш-домен.ru"
```

**Вариант B: Внутренний CA**

```bash
# Положить сертификаты от вашего CA:
sudo cp company-ca-signed.crt /etc/nginx/ssl/hcs.crt
sudo cp company-ca-signed.key /etc/nginx/ssl/hcs.key
sudo chmod 600 /etc/nginx/ssl/hcs.key
```

**Вариант C: Без SSL (только HTTP)**

В `/etc/nginx/conf.d/hcs.conf` — закомментировать секции `server :80 (redirect)` и `server :443`, раскомментировать блок `HTTP-only` внизу файла.

### Применение

```bash
# Проверить синтаксис
sudo nginx -t

# Применить
sudo systemctl reload nginx

# Автозапуск
sudo systemctl enable nginx
```

### Проверка

```bash
# HTTP (должен редиректить на HTTPS)
curl -I http://ваш-домен.ru
# HTTP/1.1 301 Moved Permanently
# Location: https://ваш-домен.ru/

# HTTPS
curl -k https://ваш-домен.ru/health
# {"status": "ok"}
```

### Ключевые параметры Nginx

| Параметр | Значение | Зачем |
|----------|----------|-------|
| `proxy_read_timeout` | 300s | Долгие API-запросы (сканы) |
| `client_max_body_size` | 50M | CSV-импорт устройств |
| `X-Forwarded-Proto` | `$scheme` | Flask знает что за HTTPS |
| `Cache-Control` на `/static/` | 7 дней | Кэширование CSS/JS |

---

## Настройка через Web UI

### Data Sources (Источники конфигураций)

Откуда HCS получает конфигурации устройств для проверок:

| Тип | Параметры | Когда использовать |
|-----|-----------|-------------------|
| **GitLab** | URL, Project ID, Token, шаблон пути | Конфиги хранятся в Git (backup/rancid) |
| **SSH** | Device type, username, port, команда | Прямой опрос оборудования |
| **NETCONF** | IP, Port (830), User/Pass | Juniper, Nokia, modern Cisco |
| **Local** | Путь к папке с файлами | Конфиги уже на диске |
| **API** | URL, auth, response path | CMDB/контроллеры с REST API |

> **Безопасность:** Пароли и токены хранятся в переменных окружения (`.env`). В UI указывается имя переменной (например `GITLAB_TOKEN`), а не сам токен.

### Inventory Sources (Источники инвентаря)

Откуда HCS получает списки устройств:

| Тип | Параметры | Когда использовать |
|-----|-----------|-------------------|
| **PostgreSQL** | host, table, column mapping | Внешняя CMDB/инвентарь |
| **REST API** | url, auth, field mapping | NetBox, DCIM и пр. |
| **Static** | JSON-список устройств | Маленькие инсталляции / тесты |

### Создание правил проверки

Типы правил:

| Тип | Описание | Пример |
|-----|----------|--------|
| `simple_match` | Regex / текстовый поиск | `service password-encryption` — must_exist |
| `block_match` | Иерархическая проверка блоков | В каждом `interface Gi*` должен быть `no ip proxy-arp` |
| `advanced_block` | Блоки с зависимостями | В `router bgp` → проверить neighbor'ов |
| `structure_check` | JSON/XML/JMESPath | Проверка structured output |
| `version_check` | Сравнение версий ПО | `os_version >= 15.2(4)M` |
| `textfsm_check` | Парсинг show-команд | Проверка полей из TextFSM-таблицы |
| `composite_check` | Комбинация правил (AND/OR) | Несколько проверок как одно правило |

### Remediation (Ansible)

Для автоматического исправления через кнопку "Fix It":

| Режим | Настройка в `.env` |
|-------|-------------------|
| **AWX/Tower** | `ANSIBLE_EXECUTOR_TYPE=awx`, `AWX_URL`, `AWX_TOKEN` |
| **SSH к Ansible-хосту** | `ANSIBLE_EXECUTOR_TYPE=ssh`, `ANSIBLE_HOST`, `ANSIBLE_USER` |
| **Локальный** | `ANSIBLE_EXECUTOR_TYPE=local` (по умолчанию) |

---

## Конфигурация (.env)

### Обязательные

| Переменная | Описание | Пример |
|-----------|----------|--------|
| `SECRET_KEY` | Ключ шифрования сессий | `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_URL` | PostgreSQL | `postgresql://hcs:password@postgres:5432/hcs` |
| `REDIS_URL` | Redis | `redis://redis:6379/0` |
| `CELERY_BROKER_URL` | Celery broker | `redis://redis:6379/0` |

### Опциональные

| Переменная | Описание | По умолчанию |
|-----------|----------|-------------|
| `GUNICORN_WORKERS` | Кол-во процессов веб-сервера | `4` |
| `SCAN_CONCURRENCY` | Потоков scan-воркера | `4` |
| `SYNC_CONCURRENCY` | Потоков sync-воркера | `2` |
| `ALERT_SCORE_THRESHOLD` | Порог алерта (%) | `80` |
| `TELEGRAM_BOT_TOKEN` | Telegram-уведомления | — |
| `TELEGRAM_CHAT_ID` | Chat ID для уведомлений | — |

---

## Бэкапы

### База данных

```bash
# Создать дамп
docker compose exec postgres pg_dump -U hcs hcs | gzip > backup-$(date +%Y%m%d).sql.gz

# Восстановить
gunzip < backup-20260402.sql.gz | docker compose exec -T postgres psql -U hcs hcs
```

### Docker volumes

```bash
docker compose stop
docker run --rm -v hcs_postgres_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/pgdata-$(date +%Y%m%d).tar.gz -C /data .
docker compose up -d
```

---

## Troubleshooting

### Контейнер не стартует

```bash
docker compose logs web           # логи веб-сервера
docker compose logs collector-scan # логи scan-воркера
```

### Миграция вручную

```bash
docker compose run --rm web migrate
```

### Сброс БД (ОСТОРОЖНО)

```bash
docker compose down -v   # удалит все данные!
docker compose up -d     # пересоздаст с нуля
```

### Shell для отладки

```bash
docker compose run --rm web shell
>>> from app.models import Device
>>> Device.query.count()
```

---

## Структура проекта

```
hcs/
├── app/
│   ├── api/            # REST API endpoints
│   ├── core/           # Registry, credentials
│   ├── engine/         # Rule evaluation engine (Strategy pattern)
│   ├── inventory/      # Device inventory providers
│   ├── models/         # SQLAlchemy ORM models
│   ├── providers/      # Config source providers (SSH, GitLab, NETCONF...)
│   ├── services/       # Scanner, InventorySync
│   ├── tasks/          # Celery tasks (scan, sync, maintenance)
│   ├── templates/      # Jinja2 UI templates
│   ├── static/         # CSS, JS, images
│   └── views.py        # Web UI routes
├── migrations/         # Alembic (Flask-Migrate) migrations
├── deploy/
│   └── nginx/          # Nginx reverse proxy config
├── Dockerfile          # Multi-stage production build
├── docker-compose.yml  # Production compose
├── docker-compose.dev.yml # Development override
├── docker-entrypoint.sh   # Universal entrypoint
├── .env.example        # Environment template (development)
├── .env.production     # Environment template (production)
└── requirements.txt
```

## License

MIT License.
