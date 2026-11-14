#!/usr/bin/env bash
# Ejecuta únicamente la verificación operativa.
set -Eeuo pipefail

raiz_pc2="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$raiz_pc2"

[[ -x .venv/bin/python ]] || {
    echo 'FALLA: primero ejecute bash pc02/desplegar.sh' >&2
    exit 1
}

.venv/bin/python -u pc02/validate.py
