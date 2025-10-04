# Fin News Hot — RADAR

Сервис для **автоматического поиска, дедупликации, ранжирования и разметки** горячих финансовых новостей с генерацией кратких объяснений (*why now*), таймлайна и черновиков постов/статей. Под капотом — сбор из RSS/Atom и обычных сайтов (autodiscovery + HTML‑harvest), ИИ‑классификация событий и аккуратная генерация черновиков.

---

## ✨ Возможности

- **Сбор новостей**
  - Поддержка RSS/Atom.
  - Если указан **homepage**, выполняется autodiscovery `<link rel="alternate" type="application/rss+xml|atom">`.
  - Если фида нет — **HTML‑harvest**: вытягиваем статьи с главной страницы (якоря с `news/press/article/business/markets`, заголовки `h1/h2/h3 a`).
  - Параллельная загрузка (флаг `--concurrency`) и ограничение `--max-per-feed`.
  - Нормализация ссылок (`utm_*`, `ref`, `gclid`, `cmp` вырезаются) → меньше дублей.

- **ИИ‑фильтр (LLM‑классификация, без “покупать/продавать”)**
  - `event_type`: `guidance | M&A | sanctions | investigation | fine | delisting | dividend/buyback | regulatory | other`
  - `materiality_ai` (0..1): оценка содержательной важности по тексту/источнику.
  - `impact_side`: `pos | neg | uncertain` — вероятное направление влияния.
  - `ai_entities`: нормализованные сущности/тикеры.
  - `risk_flags`: флаги качества (`single_source`, `low_context`, …).
  - Жёсткий JSON ответ, `temperature=0.1`, устойчивые фолбэки‑эвристики.

- **Ранжирование (hotness)**
  Учитываются новизна, авторитет источников, подтверждённость, скорость распространения, **materiality** (ключевые слова/ИИ), охват по доменам.

- **Why now & Drafts**
  Генерация «почему важно сейчас» и черновика (title/lede/bullets/quote/links) на основе `teaser + контекста из источников`. При недоступном LLM — аккуратный фолбэк.

- **API и фильтры**
  Поиск и фильтры: `q`, `types`, `min_hotness`, `event_type`, `impact_side`, `min_materiality_ai`, `order`, `limit`, `lang`.

- **Фронт‑энд (Vite + React + Tailwind)**
  Лента карточек, модалка, поиск, фильтры, ⭐закладки (localStorage), RU/EN от API, светлая/тёмная тема.


---

## 🧱 Архитектура

```
configs/                # sources.yaml или sources.d/*.yaml (источники)
api/
  app/
    main.py             # FastAPI (эндпоинты, health, фильтры, soft‑миграции)
    models.py           # Event, Source (Postgres)
    schemas.py          # Pydantic‑модели ответа API
    db.py               # async engine/session
    services/
      generate.py       # why_now + draft (LLM + фолбэк)
      ai_filter.py      # ИИ‑классификация (LLM + фолбэк)
      hotness.py        # формула ранжирования
    workers/
      ingest.py         # сбор RSS/HTML, autodiscovery, HTML‑harvest, запись в БД
frontend/
  src/                  # React + Tailwind (фильтры, модалка, RU/EN, закладки)
docker-compose.yml      # postgres + redis (локальный dev)
```

БД: Postgres, кэш/перевод (опционально) — Redis.  
API: FastAPI (uvicorn).  
LLM: OpenAI‑совместимый (OpenAI/OpenRouter). Сервис работает и **без ключей** (фолбэки).

---

## 🚀 Быстрый старт

### 0) Требования
- **Docker** + Docker Compose
- **Python 3.12** (venv)
- **Node.js 20+** (для фронта)

### 1) Клонирование
```bash
git clone git@github.com:NikitaLosev/fin-news-hot.git
cd fin-news-hot
```

### 2) Переменные окружения
```bash
cp .env.example .env
# Минимум для локалки:
# APP_ENV=dev
# BACKEND_PORT=8000
# DATABASE_URL=postgresql+asyncpg://news:news@127.0.0.1:55432/newsdb
# REDIS_URL=redis://localhost:6379/0
# ALLOWED_ORIGINS=http://localhost:5173

# Для LLM (опционально):
# OPENAI_API_KEY=sk-...
# OPENAI_BASE_URL=https://openrouter.ai/api/v1
# OPENAI_MODEL=openai/gpt-4o-mini
# OPENAI_MODEL_CLASSIFIER=openai/gpt-4o-mini
# OPENAI_MODEL_TRANSLATE=openai/gpt-4o-mini
```

> macOS + SSL, если нужны системные сертификаты:
> ```bash
> export SSL_CERT_FILE=$(python -c "import certifi; print(certifi.where())")
> export REQUESTS_CA_BUNDLE="$SSL_CERT_FILE"
> ```

### 3) Инфраструктура (Postgres/Redis)
```bash
docker compose up -d postgres redis
```

### 4) Backend (API)
```bash
cd api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Запуск
python -m uvicorn app.main:app --reload --port 8000

# Проверка
# http://127.0.0.1:8000/health  → { ok, events, sources, last_source }
```

### 5) Сбор новостей (воркер)
```bash
cd api && source .venv/bin/activate
export DATABASE_URL="postgresql+asyncpg://news:news@127.0.0.1:55432/newsdb"

# Один файл
python -u -m app.workers.ingest --sources ../configs/sources.yaml --concurrency 8 --max-per-feed 40

# Директория пакетов источников (создайте configs/sources.d/*.yaml)
# python -u -m app.workers.ingest --sources ../configs/sources.d --concurrency 8 --max-per-feed 40
```

В логах:
- `discovered … -> items=NN` — найден RSS/Atom через `<link rel="alternate">`
- `harvested NN items from HTML` — собрали статьи с homepage
- Итог: `[ingest] … new_events=NNN, new_sources=MMM`

### 6) Frontend
```bash
cd ../frontend
npm i
npm run dev
# http://localhost:5173
```

---

## 📡 API

База: `http://127.0.0.1:8000`

### `GET /health`
Статус, число событий/источников, время последнего источника.

### `GET /events`
Параметры:
- `q` — поиск по заголовку  
- `types` — CSV: `regulator,news,ir,exchange,aggregator`  
- `min_hotness` — 0..1  
- `event_type` — `regulatory|M&A|sanctions|...`  
- `impact_side` — `pos|neg|uncertain`  
- `min_materiality_ai` — 0..1  
- `order` — `hotness|recent`  
- `offset`, `limit`  
- `lang` — `ru|en`

### `GET /events/{id}`
Параметры: `lang` — `ru|en`

### `POST /events/{id}/generate`
Генерация `why_now + draft` (учитывает teaser/контент). `lang` — опционален.

---

## 🗃️ Модель данных

**Event**
- `id`, `headline`, `hotness`, `why_now`, `entities`, `timeline`, `draft`, `confirmed`
- `dedup_group`, `first_seen`
- **AI‑поля**: `event_type`, `materiality_ai`, `impact_side`, `ai_entities`, `risk_flags`

**Source**
- `event_id`, `url`, `type`, `first_seen`

*Дедупликация*: по **канонизированной ссылке** (fallback по заголовку).

---

## 🧠 ИИ‑модули

- **Классификация (`services/ai_filter.py`)**  
  Строгий JSON, `temperature=0.1`; фолбэк‑эвристики по ключевым словам и тикерам (капс паттерны).  
  В ранжировании используется `materiality_combined = max(materiality_kw, materiality_ai)`.

- **Генерация (`services/generate.py`)**  
  Редактура подготовленного черновика (не «с нуля»): `seed = why_now + фрагменты контента` → LLM → валидные JSON‑структуры и фолбэк.

- **Перевод (`services/translate.py`)**  
  `lang=ru|en` для API; кэш в Redis; без ключа возвращает исходный текст (не падает).

---

## ⚙️ Конфигурация источников

### Один файл: `configs/sources.yaml`
```yaml
- {name: "SEC Press", url: "https://www.sec.gov/news/pressreleases.rss", type: "regulator", country: "US"}
- {name: "ECB", url: "https://www.ecb.europa.eu", type: "regulator", country: "EU"}   # homepage: autodiscovery/harvest
```

### Пакеты: `configs/sources.d/*.yaml`
```
configs/sources.d/
  00_regulators_us.yaml
  01_regulators_eu_uk.yaml
  02_exchanges.yaml
  03_newswires.yaml
  04_media.yaml
```
Запуск: `--sources ../configs/sources.d`

---

## 🧰 Troubleshooting

- **SSL ошибки на macOS**  
  `export SSL_CERT_FILE=$(python -c "import certifi; print(certifi.where())")`  
  `export REQUESTS_CA_BUNDLE="$SSL_CERT_FILE"`

- **Postgres порт занят**  
  Отредактируй `docker-compose.yml` и `DATABASE_URL` (например, `55432:5432`).

- **`UndefinedColumnError: events.event_type`**  
  Запусти API один раз (он делает soft‑миграции) **ИЛИ** воркер (тоже выполнит `ALTER TABLE IF NOT EXISTS`).

- **`InterfaceError: another operation is in progress` / `ResourceClosedError`**  
  Воркера уже перевели на per‑item транзакции и отдельную сессию на источник. Если повторяется — снизь `--concurrency` до 6–8.

- **`items=0` на многих сайтах**  
  Часть доменов без RSS и с антиботом. Для ключевых добавляй официальные RSS; увеличивай `--max-per-feed`; при необходимости исключай «проблемные» домены.

---

## 🗺️ Roadmap

- ETag/Last‑Modified кэш на фиды/страницы  
- Backoff‑ретраи и «чёрный список» доменов‑шумовиков  
- Event‑study (post‑event) с рыночными данными  
- Экспорт шортлистов (CSV/Markdown)  
- UI‑фильтры по `event_type/impact/materiality_ai` + бейджи

---

## 🔒 Безопасность

Не коммить `OPENAI_API_KEY`/секреты. Используй `.env` локально и secrets в CI.

---

## 📄 Лицензия

MIT (или укажи свою).
