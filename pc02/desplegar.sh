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

if [[ -d pc02/runtime && -f pc02/escenario02.runtime.yml ]]; then
    echo 'Reutilizando runtime y las configuraciones guardadas.'
elif [[ ! -e pc02/runtime && ! -e pc02/escenario02.runtime.yml ]]; then
    "$python_pc2" pc02/prepare_runtime.py
else
    fallar_pc2 'runtime está incompleto; revise la preparación.'
fi

if [[ ! -e pc02/escenario02.runtime.yml.annotations.json ]]; then
    cp pc02/escenario02.yml.annotations.json \
       pc02/escenario02.runtime.yml.annotations.json
fi

containerlab validate -t pc02/escenario02.runtime.yml

echo '=== 3/3: DESPLIEGUE ==='
if (( existentes_pc2 > 0 )); then
    echo 'Recreando la red de esta carpeta; runtime se conserva.'
    sudo containerlab destroy \
      -t pc02/escenario02.runtime.yml --cleanup
fi

sudo containerlab deploy \
  -t pc02/escenario02.runtime.yml --max-workers 4

echo 'OK: red desplegada. Continúe con bash pc02/configurar.sh'
