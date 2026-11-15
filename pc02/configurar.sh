#!/usr/bin/env bash
# Configura y guarda por SSH.
set -Eeuo pipefail

raiz_pc2="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$raiz_pc2"

# La consola muestra el resultado final; el detalle completo queda en un registro.
mkdir -p pc02/logs/etapas
registro_pc2="$(mktemp "$raiz_pc2/pc02/logs/etapas/configuracion-XXXXXXXX.log")"
exec 3>&1 4>&2
informar_salida_pc2() {
    estado_pc2=$?
    trap - EXIT
    if (( estado_pc2 != 0 )); then
        printf 'FALLA: configuracion. Registro: %s\n' "$registro_pc2" >&4
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

espera_pc2="${PC2_ESPERA:-60}"
[[ "$espera_pc2" =~ ^[0-9]+$ ]] || {
    echo 'FALLA: PC2_ESPERA debe ser un entero de segundos.' >&2
    exit 1
}

.venv/bin/python -u pc02/run.py --method netmiko --all

printf 'Esperando convergencia: %s segundos.\n' "$espera_pc2"
sleep "$espera_pc2"

grep -Fxq 'Aplicaciones confirmadas: 30/30' "$registro_pc2"
exec 1>&3 2>&4
printf 'Routers configurados: 30/30\n'
echo 'TODOS LOS DISPOSITIVOS CONFIGURADOS'
