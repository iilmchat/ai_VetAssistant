# Обучение на удаленном GPU-сервере (T-016)

Документ описывает развертывание окружения на арендованном сервере Selectel
с образом **Unsloth VM** (Ubuntu 24.04, CUDA и PyTorch уже установлены).

## 1. Что делает `scripts/setup_remote.sh`

Скрипт идемпотентен и выполняет:

1. Устанавливает `git` и системные пакеты: `python3-pip`, `python3-venv`,
   `ca-certificates`, `curl`, `make`.
2. Ставит зависимости сборки `build-essential`, `zlib1g-dev`, `libxml2-dev`
   и заголовочные файлы Python для Triton. Версия Python определяется
   динамически (`python3.14-dev` / `libpython3.14-dev`, fallback `python3-dev`).
3. Клонирует репозиторий по `GITHUB_TOKEN`/`REPO_URL` или использует уже
   существующий каталог (например, скопированный через `scp`).
4. Создает и активирует `.venv`.
5. Устанавливает `requirements-train.txt`, затем удаляет несовместимый
   `xformers` из образа Unsloth, и ставит `dvc[s3]`.
6. Настраивает DVC-remote `selectel`:
   - URL: `s3://vetassistant-data/dvc`;
   - endpoint: `https://s3.ru-7.storage.selcloud.ru`;
   - регион: `ru-7`.
7. Записывает S3-ключи **только** в `.dvc/config.local` (права `600`,
   файл игнорируется Git).
8. Выполняет `dvc pull` и проверяет доступность CUDA/PyTorch.

## 2. Подготовка S3-ключей

Ключи Selectel не хранятся в репозитории. Передайте их одним из способов:

- интерактивно — скрипт сам запросит `access_key_id` и `secret_access_key`
  (secret не отображается при вводе);
- через переменные окружения:
  ```bash
  export S3_ACCESS_KEY_ID="..."
  export S3_SECRET_ACCESS_KEY="..."
  ```
  Также поддерживаются стандартные `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.
- заранее скопировав `.dvc/config.local` с локальной машины:
  ```bash
  scp .dvc/config.local root@<server-ip>:~/ai_VetAssistant/.dvc/config.local
  ```
  Если файл уже содержит оба ключа, скрипт не будет их запрашивать.

## 3. Приватный GitHub-репозиторий

Если репозиторий закрыт, сервер не сможет клонировать его без авторизации.
Передайте GitHub Personal Access Token с правом чтения репозитория:

```bash
export GITHUB_TOKEN="github_pat_..."
bash scripts/setup_remote.sh
```

Скрипт клонирует `https://$GITHUB_TOKEN@github.com/iilmchat/ai_VetAssistant.git`
и сразу убирает токен из `.git/config` (origin снова указывает на URL без
токена). Токен не выводится в лог. Без `GITHUB_TOKEN` используется обычный
URL `https://github.com/iilmchat/ai_VetAssistant.git`.

Если каталог `~/ai_VetAssistant` уже существует (например, вы скопировали его
через `scp`/`rsync`), скрипт **пропускает клонирование** и продолжает
настройку в существующем каталоге. В этом случае обновление исходников нужно
делать самостоятельно (`git pull` или повторное копирование).

## 4. Запуск на сервере

Подключитесь по SSH:

```bash
ssh root@<server-ip>
```

### Вариант A: репозиторий уже склонирован

Для приватного репозитория клонируйте его с токеном, затем запустите
установку (скрипт увидит существующий каталог и пропустит clone):

```bash
git clone "https://${GITHUB_TOKEN}@github.com/iilmchat/ai_VetAssistant.git" \
  ~/ai_VetAssistant
cd ~/ai_VetAssistant
bash scripts/setup_remote.sh
```

### Вариант B: чистая машина

Скопируйте скрипт на сервер и запустите — он сам клонирует проект. Для
приватного репозитория скачайте скрипт с токеном:

```bash
curl -fsSL \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  https://raw.githubusercontent.com/iilmchat/ai_VetAssistant/main/scripts/setup_remote.sh \
  -o /tmp/setup_remote.sh
bash /tmp/setup_remote.sh
```

Либо просто передайте файл по scp:

```bash
scp scripts/setup_remote.sh root@<server-ip>:/tmp/setup_remote.sh
ssh root@<server-ip> "bash /tmp/setup_remote.sh"
```

По умолчанию проект будет развернут в `~/ai_VetAssistant`. Другие параметры
можно переопределить переменными:

```bash
REPO_URL=https://github.com/iilmchat/ai_VetAssistant.git \
PROJECT_DIR=/opt/vetassistant \
bash /tmp/setup_remote.sh
```

Для неинтерактивного запуска (CI) заранее задайте `S3_ACCESS_KEY_ID` и
`S3_SECRET_ACCESS_KEY`; иначе скрипт попросит их ввести и завершится с ошибкой
при отсутствии TTY.

## 5. После установки

Активируйте окружение в текущей SSH-сессии:

```bash
source ~/ai_VetAssistant/.venv/bin/activate
cd ~/ai_VetAssistant
```

Проверьте GPU и данные:

```bash
nvidia-smi
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
dvc status
```

`dvc status` должен показать, что данные на месте. Если нужно обновить
датасеты вручную:

```bash
python scripts/sync_data.py pull
```

Повторный запуск `setup_remote.sh` безопасен: существующий каталог не
клонируется, виртуальное окружение переиспользуется. Обновление исходников в
существующем каталоге выполняйте вручную (`git pull` или повторный `scp`).

## 6. Локальная проверка перед запуском

Эти команды можно запускать на Windows/CPU **без GPU, Unsloth и PyTorch**.
Они проверяют конфиг, JSONL-диалоги и показывают ChatML-превью:

```powershell
# Если venv активирован:
python scripts/train_sft.py --dry-run
python scripts/train_sft.py --dry-run --limit 3 --preview-count 2
python scripts/merge_lora.py --dry-run

# Если venv не активирован (Windows):
.\.venv\Scripts\python.exe scripts\train_sft.py --dry-run
.\.venv\Scripts\python.exe scripts\merge_lora.py --dry-run
```

Что проверяет `train_sft.py --dry-run`:

- YAML-конфиг и все гиперпараметры;
- наличие и валидность `data/train.jsonl` / `data/val.jsonl`;
- количество диалогов, распределение по темам, число реплик;
- первые диалоги в ChatML-формате (для визуальной проверки);
- ничего не пишет на диск и не загружает токенизатор/модель.

`merge_lora.py --dry-run` проверяет пути adapter/output и конфиг, не загружая
Unsloth. На сервере после установки зависимостей полезен короткий smoke-прогон:

```bash
make smoke
# эквивалент: python scripts/train_sft.py --limit 20 --max-steps 10
```

Он проверяет весь GPU-пайплайн (загрузка Qwen3-8B, tokenizer, SFTTrainer,
сохранение adapter) до полного 2–3-часового запуска.

## 7. Запуск обучения

Скрипт обучения SFT добавлен в T-015. Полный запуск:

```bash
source ~/ai_VetAssistant/.venv/bin/activate
cd ~/ai_VetAssistant
python scripts/train_sft.py --config configs/train_sft.yaml
# или короткая команда:
make train
```

После завершения LoRA-адаптер будет в `outputs/sft_qwen3_8b/adapter`.
Для получения merged 16-bit модели:

```bash
python scripts/merge_lora.py --config configs/train_sft.yaml
# или:
make merge
```

Результат: `outputs/sft_qwen3_8b/merged`.

## 8. Фоновый запуск на сервере

Обучение занимает 2–3 часа, поэтому запускайте его через `nohup`, чтобы
процесс пережил закрытие SSH-сессии:

```bash
cd ~/ai_VetAssistant
source .venv/bin/activate
nohup python scripts/train_sft.py > train.log 2>&1 &
```

Проверить, что процесс жив:

```bash
tail -f train.log
```

`Ctrl+C` в этом режиме останавливает только `tail`, обучение продолжается.
Дополнительно можно проверить процесс и GPU:

```bash
pgrep -af train_sft.py
nvidia-smi
```

Остановить обучение при необходимости:

```bash
pkill -f train_sft.py
```

## 9. Конвертация в GGUF

Скрипт `scripts/convert_to_gguf.py` конвертирует merged-модель из
`models/merged-model` в GGUF Q4_K_M и Q5_K_M. Его можно запускать локально
(Windows/Linux с Python, Git и CMake) или на сервере после завершения
обучения.

```bash
python scripts/convert_to_gguf.py
```

Скрипт автоматически:

- клонирует официальный `llama.cpp` в `models/llama.cpp`, если его ещё нет;
- устанавливает зависимости из `llama.cpp/requirements.txt`;
- запускает `convert_hf_to_gguf.py` с `--outtype f16`;
- собирает `llama-quantize` через CMake, если бинарника нет;
- создаёт в `models/gguf/`:
  - `qwen3-8b-vet-f16.gguf`;
  - `qwen3-8b-vet-Q4_K_M.gguf`;
  - `qwen3-8b-vet-Q5_K_M.gguf`.

Проверка логики без запуска тяжёлых процессов:

```bash
python scripts/convert_to_gguf.py --dry-run
```

Для Windows нужны CMake и Visual Studio Build Tools (C++); для Ubuntu —
`build-essential` и `cmake` (setup-скрипт ставит build-essential отдельно).
Пути можно переопределить: `--model-dir`, `--output-dir`, `--llama-dir`.

## 10. Локальный веб-интерфейс Streamlit

После запуска FastAPI-сервера (см. `README.md`) можно открыть браузерный чат
с моделью:

```bash
pip install -e .
streamlit run app/ui.py
```

На Windows, если команда `streamlit` не найдена в PATH:

```powershell
python -m streamlit run app/ui.py
```

UI доступен на `http://localhost:8501` и обращается к
`POST http://127.0.0.1:8000/v1/chat/completions`. Поддерживаются потоковый
вывод ответа, история в `st.session_state`, слайдер `temperature` и очистка
истории. Если API выключен, интерфейс покажет:
«Сервер ветеринара спит, включите uvicorn».

## 11. Диагностика

- **`apt-get: Permission denied`** — запускайте от `root` или через пользователя
  с `sudo`.
- **`dvc pull`: 403/401** — проверьте ключи и права на бакет
  `vetassistant-data`; перезапишите их:
  `dvc remote modify --local selectel access_key_id ...`.
- **`torch.cuda.is_available() == False`** — проверьте, что используется образ
  Unsloth VM с драйвером NVIDIA и запущен `nvidia-smi`.
- **Нет `requirements-train.txt`** — обновите репозиторий до `main`.
