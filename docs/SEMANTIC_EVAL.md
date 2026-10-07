# Испытание локальной мультиязычной модели

Это отдельный CPU-пилот, не переключение приложения и не подтверждение юридического качества.
Модель: [paraphrase-multilingual-MiniLM-L12-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2).
Карточка указывает 384 измерения, 50 языков, лицензию Apache-2.0 и лимит 128 токенов.
Для воспроизводимости загрузчик использует ревизию
`e8f8c211226b894fcb81acc59f3b34ba3efd5f42`, а не меняющийся main.
Это инженерный кандидат; выбор для эксплуатации требует сравнения моделей и проверки лицензий.

## Окружение

Основной `uv.lock` не меняется. `requirements-semantic.lock` фиксирует дополнительное
окружение Linux x86_64 / Python 3.12 с хешами, согласованное с экспортом базового lock.
Не считать этот файл универсальным lock для Windows/macOS.
CPU-пакеты PyTorch выбираются через `--torch-backend cpu`; остальное — PyPI.
`requirements-semantic.txt` — вход резолвера, не инструкция установки неприкреплённых версий.

Сборка требует сети и места для PyTorch, зависимостей и модели (~470 МБ весов).
Модель хранится отдельно от образа, каталог `models/` исключён из Git и Docker context.

```powershell
docker build -f Dockerfile.semantic -t ai-office-semantic:validation .
$workspace = (Get-Location).Path
docker run --rm --mount "type=bind,source=$workspace,target=/workspace" ai-office-semantic:validation uv run --no-sync python scripts/download_semantic_model.py /workspace/models/minilm-multilingual-e8f8c211
```

Запускайте из корня проекта. Загрузчик обращается только за публичной моделью, не отправляет
документы и не использует HF-токен. Загружаются разрешённые tokenizer/config файлы и safetensors,
не pickle-веса, ONNX или Python-файлы. Готовый снимок содержит `snapshot.json` с SHA-256 файлов.
Существующий каталог не перезаписывается; после ошибки частичный снимок не публикуется.
Перед эксплуатацией отдельно одобрите и храните неизменяемый снимок.

## Сравнение на одном наборе

`tests/fixtures/semantic_eval.json`: восемь синтетических русскоязычных документов,
восемь русских перефразировок, четыре англоязычных запроса и шесть отрицательных случаев.
Набор написан разработчиком до первого прогона; он не является независимым holdout.
Не обучать модель и не подбирать порог на нём с последующим заявлением независимого результата.

Порог 0.3 и top-k=3 сохраняют прежние настройки пилота. Оба прогона ниже запрещают сеть,
используют временную SQLite БД, не вызывают LLM и сохраняют новые JSON-отчёты:

```powershell
docker run --rm --network none --mount "type=bind,source=$workspace,target=/workspace" ai-office-semantic:validation uv run --no-sync python scripts/eval_retrieval.py --suite tests/fixtures/semantic_eval.json --output /workspace/output/semantic-mock-v1.json
docker run --rm --network none -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 --mount "type=bind,source=$workspace,target=/workspace" ai-office-semantic:validation uv run --no-sync python scripts/eval_retrieval.py --suite tests/fixtures/semantic_eval.json --model-path /workspace/models/minilm-multilingual-e8f8c211 --output /workspace/output/semantic-minilm-v1.json
```

Для повторного прогона выберите новые имена отчётов. Наличие отчёта не означает успех:
`passed` требует всех четырёх метрик >=0.99. Опция `--check` также возвращает exit 1 при провале.
Без `--check` exit 0 означает только, что измерение завершилось.
Отчёт содержит ID модели по хешу снимка, версии библиотек, хеш набора, порог, размеры,
метрики, результаты/оценки каждого запроса и exact-set-rate по категориям.
Время исключает первоначальную загрузку модели; это не полноценный performance benchmark.

Сложный отрицательный запрос о законном штрафе намеренно требует пустой выдачи:
в корпусе есть срок оплаты, но нет нормы о штрафах. Тематически близкий текст не доказывает
наличия ответа. Этот консервативный тест проверяет границу применимости retrieval,
не заменяя отдельную проверку достаточности источников при юридическом анализе.

## Результаты первого прогона, 2026-08-27

Одинаковые восемь документов, 12 положительных и шесть отрицательных запросов; top-k=3.
Результаты ниже — только для этого набора, без подбора порога по его ответам.

| Метрика | Mock | MiniLM, порог 0.3 |
|---|---:|---:|
| Recall@3 | 0.0833 | 1.0000 |
| Средняя precision выдачи | 0.0278 | 0.5972 |
| MRR@3 | 0.0417 | 0.9167 |
| Доля пустых ответов на отрицательные запросы | 0.8333 | 0.6667 |

MiniLM находит все 12 требуемых источников, но не всегда ставит их первыми и добавляет шум.
Запрос о варке спагетти вернул рабочий распорядок (score 0.3017); запрос о законном штрафе —
тематически близкие документы, не содержащие требуемой нормы. Все три фильтра доступа прошли.
**Gate не пройден**, `--check` вернул exit 1. Порог и default mock не изменены.

Сырые отчёты: [mock](../output/semantic-mock-v1.json),
[MiniLM](../output/semantic-minilm-v1.json). Хеш набора:
`aa8756867ebc8e256d57090d3ad797d73dac1efd59b17a39dcb3d12c82b817e8`.
ID модели:
`st-local-v1:7dda2fda3e823840ab939006044ab84d6c5a16234a50bcebb8e74a5cdf957d8b`.
Это исторический прогон до token-aware разбиения. Текущий код использует namespace
st-local-v2; для него выбирайте новые имена отчётов. Старые отчёты не переписываются.
Стек: sentence-transformers 5.7.0, torch 2.13.0+cpu, transformers 5.16.1.

С установленным стеком прошли 125 тестов, включая PostgreSQL; отдельно без сети —
два теста настоящей модели (нормализация/повторяемость и отказ от усечения длинного текста).
Прежний mock eval --check и HTTP smoke прошли. Библиотека предупреждает о будущем
переименовании get_sentence_embedding_dimension; текущий вызов работает.
Для двух opt-in тестов задайте TEST_SEMANTIC_MODEL_PATH и запускайте tests/semantic
в контейнере с --network none. Без этой переменной тесты пропускаются.

Следующая работа: отдельный calibration/holdout набор, сравнение моделей/переранжирования,
проверка достаточности источников и оценка новых границ чанков. Нельзя считать задачу поиска
готовой к эксплуатации на основании одного высокого recall.

## Обновление lock-файла

В Linux-контейнере с Python 3.12 и uv 0.12.5, из корня проекта:

```sh
uv export --locked --no-hashes --no-emit-project --output-file requirements-base-constraints.txt
uv pip compile requirements-semantic.txt --constraints requirements-base-constraints.txt --torch-backend cpu --python-version 3.12 --generate-hashes --output-file requirements-semantic.lock
```

После изменения базового lock повторите экспорт, компиляцию, `uv pip check`, тесты и оценку.
Запуск с установленным дополнительным стеком требует `uv run --no-sync`: обычный sync может
удалить его. CI базового проекта не скачивает тяжёлую модель автоматически.
