#!/usr/bin/env bash
# Configura y guarda por SSH.
set -Eeuo pipefail

raiz_pc2="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$raiz_pc2"

[[ -x .venv/bin/python ]] || {
    echo 'FALLA: primero ejecute bash pc02/desplegar.sh' >&2
    exit 1
}

espera_pc2="${PC2_ESPERA:-60}"
[[ "$espera_pc2" =~ ^[0-9]+$ ]] || {
    echo 'FALLA: PC2_ESPERA debe ser un entero de segundos.' >&2
    exit 1
}

.venv/bin/python -u pc02/run.py --method netmiko --all

printf 'Esperando convergencia: %s segundos.\n' "$espera_pc2"
sleep "$espera_pc2"

echo 'OK: configuración terminada. Continúe con bash pc02/validar.sh'
