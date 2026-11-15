#!/usr/bin/env bash
# Prepara y despliega PC2.
set -Eeuo pipefail

raiz_pc2="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$raiz_pc2"

fallar_pc2() { printf 'FALLA: %s\n' "$*" >&2; exit 1; }
trap 'printf "FALLA: despliegue detenido en la línea %s.\n" "$LINENO" >&2' ERR

for programa_pc2 in python3 docker containerlab sudo; do
    command -v "$programa_pc2" >/dev/null ||
        fallar_pc2 "Falta instalar $programa_pc2."
done

echo '=== 1/3: ENTORNO Y DEPENDENCIAS ==='
if [[ ! -x .venv/bin/python ]]; then
    python3 -m venv .venv
fi

python_pc2="$raiz_pc2/.venv/bin/python"
"$python_pc2" -m pip install -r requirements.txt

sudo -v
if ! docker info >/dev/null 2>&1; then
    sudo systemctl start docker
fi

docker info >/dev/null 2>&1 ||
    fallar_pc2 'El usuario actual no puede acceder a Docker.'

existentes_pc2="$("$python_pc2" - "$raiz_pc2" <<'PC2_COMPROBAR'
import json
import os
from pathlib import Path
import subprocess
import sys
import yaml

base = Path(sys.argv[1])
topologia = yaml.safe_load((base / 'pc02/escenario02.yml').read_text())
imagen = topologia['topology']['defaults']['image']

resultado = subprocess.run(
    ['docker', 'image', 'inspect', imagen],
    capture_output=True, text=True,
)
if resultado.returncode:
    raise SystemExit(f'FALLA: falta cargar la imagen del curso {imagen}.')

ids = subprocess.check_output(
    ['docker', 'ps', '-aq', '--filter',
     f"label=containerlab={topologia['name']}"],
    text=True,
).split()

if ids:
    contenedores = json.loads(subprocess.check_output(
        ['docker', 'inspect', *ids], text=True
    ))
    esperado = (base / 'pc02/runtime/configs').resolve()

    for contenedor in contenedores:
        montajes = [
            m for m in contenedor['Mounts']
            if m['Destination'] == '/etc/frr'
        ]
        if len(montajes) != 1:
            raise SystemExit('FALLA: montaje del laboratorio no reconocido.')

        fuente = Path(montajes[0]['Source']).resolve()
        if os.path.commonpath([str(fuente), str(esperado)]) != str(esperado):
            raise SystemExit(
                f'FALLA: el laboratorio pertenece a otra carpeta: {fuente}. '
                'Ejecute desplegar.sh desde la copia que lo desplegó.'
            )

print(len(ids))
PC2_COMPROBAR
)"

echo '=== 2/3: MÓDULOS Y TOPOLOGÍA ==='
sudo modprobe mpls_router
sudo modprobe mpls_iptunnel

# Validamos y generamos las configuraciones finales sin aplicarlas todavía.
# Esto permite detectar errores del inventario antes de interrumpir la red.
"$python_pc2" pc02/build_configs.py

if (( existentes_pc2 > 0 )); then
    [[ -f pc02/escenario02.runtime.yml ]] ||
        fallar_pc2 'Falta la topología del laboratorio activo; no se modifica.'
    echo 'Retirando el laboratorio de esta carpeta para un arranque vacío.'
    sudo containerlab destroy \
      -t pc02/escenario02.runtime.yml --cleanup
fi

if [[ -e pc02/runtime || -e pc02/escenario02.runtime.yml ]]; then
    mkdir -p "$HOME/Respaldos-PC2"
    respaldo_pc2="$(mktemp -d "$HOME/Respaldos-PC2/vacio-XXXXXXXX")"
    for anterior_pc2 in pc02/runtime pc02/escenario02.runtime.yml; do
        if [[ -e "$anterior_pc2" ]]; then
            sudo mv -- "$anterior_pc2" "$respaldo_pc2/"
        fi
    done
    printf 'Estado anterior respaldado en: %s\n' "$respaldo_pc2"
fi

"$python_pc2" pc02/prepare_runtime.py
cp pc02/escenario02.yml.annotations.json \
   pc02/escenario02.runtime.yml.annotations.json
containerlab validate -t pc02/escenario02.runtime.yml

echo '=== 3/3: DESPLIEGUE SIN CONFIGURACIÓN DE LA PRÁCTICA ==='
sudo containerlab deploy \
  -t pc02/escenario02.runtime.yml --max-workers 4

"$python_pc2" pc02/check_empty.py
echo 'OK: 30 routers sin configuración de la práctica. Ejecute bash pc02/configurar.sh'
