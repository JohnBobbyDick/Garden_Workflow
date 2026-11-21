#!/bin/bash
set -euo pipefail

# Проверить Swift-клиент и FastAPI из одной копии репозитория.
umask 077
swift_dir="$(cd "$(dirname "$0")" && pwd)"
repo_dir="$(dirname "$swift_dir")"
server_dir="$repo_dir/backend"
fixtures="$repo_dir/fixtures/organizer-training"
data_dir="${GARDEN_CHECK_DIR:-$HOME/Library/Caches/GardenSwift/LocalCheck}"
build_dir="$data_dir/build"
server_url="http://127.0.0.1:17880"
if [[ ! -d "$fixtures/training-project" || ! -f "$server_dir/alembic.ini" ]]; then
    echo "Запустите файл из каталога GardenSwift в репозитории Lampochki."
    exit 1
fi
if /usr/sbin/lsof -nP -iTCP:17880 -sTCP:LISTEN >/dev/null; then
    echo "Порт 17880 уже занят. Если открыта предыдущая проверка Garden, завершите её и повторите запуск."
    exit 1
fi
mkdir -p "$data_dir"
python="$server_dir/.venv/bin/python"
if [[ ! -x "$python" ]]; then
    if ! command -v uv >/dev/null; then
        echo "Установите зависимости backend по README проекта или установите uv и повторите запуск."
        exit 1
    fi
    python="$data_dir/venv/bin/python"
    if [[ ! -x "$python" ]]; then
        uv venv --python '>=3.12' "$data_dir/venv"
    fi
    uv pip install --python "$python" -r "$server_dir/pyproject.toml"
fi
export PYTHONDONTWRITEBYTECODE=1
export CLANG_MODULE_CACHE_PATH="$data_dir/swift-modules"
build_args=(--package-path "$swift_dir" --scratch-path "$build_dir" --manifest-cache none --disable-sandbox)
echo "1/3  Сборка Swift и тесты клиента"
swift build "${build_args[@]}"
bin_dir="$(swift build "${build_args[@]}" --show-bin-path)"
"$bin_dir/GardenCoreTests"

echo "2/3  Локальный сервер и проверка учебного проекта"
export APP_DATA_DIR="$data_dir"
export APP_DATABASE_URL="sqlite:///$data_dir/garden.db"
export APP_INPROCESS_WORKER=true APP_SCAN_ROOTS="$fixtures" APP_PUBLIC_URL="$server_url"
cd "$server_dir"
"$python" -m alembic upgrade head
"$python" -m uvicorn app.main:app --host 127.0.0.1 --port 17880 --no-access-log >"$data_dir/server.log" 2>&1 &
server_pid=$!
stop_server() {
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
}
trap stop_server EXIT
trap 'exit 130' INT TERM
ready=false
for ((attempt=0; attempt<60; attempt++)); do
    if ! kill -0 "$server_pid" 2>/dev/null; then break; fi
    if curl --noproxy '*' --max-time 2 -fsS "$server_url/api/healthz" >/dev/null 2>&1; then ready=true; break; fi
    sleep 0.5
done
if [[ "$ready" != true ]]; then
    echo "Сервер не запустился. Журнал: $data_dir/server.log"
    exit 1
fi
GARDEN_TEST_SERVER="$server_url" GARDEN_TEST_FIXTURES="$fixtures" "$bin_dir/GardenLiveTests"

echo "3/3  Проверка пройдена. На учебном проекте получено 15 находок."
if [[ "${1:-}" == "--check-only" ]]; then exit 0; fi
echo "В окне Garden укажите адрес $server_url и создайте свой локальный аккаунт."
echo "Для ручной проверки выберите «…» → «Шаблоны» → «Проверка секретов»."
echo "В поле «Параметры (JSON)» вставьте строку целиком:"
printf '{"src.path":"%s/training-project"}\n' "$fixtures"
echo "Оставьте Терминал открытым. При выходе из приложения сервер остановится."
"$bin_dir/GardenApp"
