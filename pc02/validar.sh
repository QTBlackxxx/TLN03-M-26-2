#!/usr/bin/env bash
# Ejecuta únicamente la verificación operativa.
set -Eeuo pipefail

raiz_pc2="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$raiz_pc2"

# La consola muestra el resultado final; el detalle completo queda en un registro.
mkdir -p pc02/logs/etapas
registro_pc2="$(mktemp "$raiz_pc2/pc02/logs/etapas/validacion-XXXXXXXX.log")"
exec 3>&1 4>&2
informar_salida_pc2() {
    estado_pc2=$?
    trap - EXIT
    if (( estado_pc2 != 0 )); then
        printf 'FALLA: validacion. Registro: %s\n' "$registro_pc2" >&4
        tail -n 35 "$registro_pc2" >&4
    fi
    exit "$estado_pc2"
}
trap informar_salida_pc2 EXIT
exec >"$registro_pc2" 2>&1

[[ -x .venv/bin/python ]] || {
    echo 'FALLA: primero ejecute bash pc02/desplegar.sh' >&2
    exit 1
}

.venv/bin/python -u pc02/validate.py

grep -Fxq 'Nodos validados: 30/30' "$registro_pc2"
exec 1>&3 2>&4
echo 'RED CONFIGURADA FUNCIONAL'
