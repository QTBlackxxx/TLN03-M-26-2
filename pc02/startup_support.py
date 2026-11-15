"""Prepara arranque con init y operaciones FRR serializadas por contenedor."""

import json
import os
from pathlib import Path
import subprocess


SERIAL_WRAPPER = '''#!/bin/bash
# Un solo start/stop/restart FRR a la vez dentro de este contenedor.
set -eu
exec flock --exclusive --close --wait 70 /run/frr/pc2-lifecycle.lock \\
    /bin/bash /pc2-startup/watchfrr-worker.sh "$@"
'''

SERIAL_WORKER = '''#!/bin/bash
# flock mantiene el bloqueo; los daemons no heredan su descriptor.
set -u
record=/run/frr/pc2-lifecycle.log
printf '%s START pid=%s action=%s target=%s\\n' \\
    "$(date -Iseconds)" "$$" "${1-}" "${2-all}" >> "$record"
/bin/bash /pc2-startup/watchfrr-original.sh "$@"
result=$?
printf '%s END pid=%s action=%s target=%s rc=%s\\n' \\
    "$(date -Iseconds)" "$$" "${1-}" "${2-all}" "$result" >> "$record"
exit "$result"
'''


def command(args, timeout=90):
    """Ejecuta Docker sin shell y conserva los errores relevantes."""
    try:
        result = subprocess.run(args, capture_output=True, text=True,
                                timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"No se pudo ejecutar {args[0]}: {error}") from error
    if result.returncode:
        raise RuntimeError(f"Comando fallido: {args!r}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def prepare_startup(base, topology):
    """Monta init y serializador conservando la imagen y start.sh originales."""
    base = Path(base).resolve()
    image = topology["topology"]["defaults"]["image"]
    metadata = json.loads(command(["docker", "image", "inspect", image]))[0]
    config = metadata["Config"]
    if config.get("Entrypoint") != ["/usr/local/bin/start.sh"] or config.get("Cmd"):
        raise RuntimeError("La imagen tiene un arranque distinto al revisado; detener y revisar")
    for name, node in topology["topology"]["nodes"].items():
        if node.get("entrypoint") not in (None, "/pc2-startup/docker-init -- /usr/local/bin/start.sh") or node.get("cmd"):
            raise RuntimeError(f"{name}: arranque personalizado no reconocido")
        for bind in node.get("binds", []):
            if bind.split(":")[1] == "/usr/lib/frr/watchfrr.sh" and "./runtime/startup/" not in bind:
                raise RuntimeError(f"{name}: watchfrr.sh ya tiene otro montaje")

    directory = base / "runtime" / "startup"
    directory.mkdir(parents=True, exist_ok=True)
    # Este auxiliar no inicia FRR ni tiene red. Obtiene el init de Docker y
    # conserva una copia exacta del manejador de servicios de la imagen.
    command([
        "docker", "run", "--rm", "--network", "none", "--init",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--mount", f"type=bind,src={directory},dst=/out",
        "--entrypoint", "/bin/bash", image, "-ec",
        "command -v flock >/dev/null; "
        "test -r /usr/lib/frr/frrcommon.sh; "
        "cp -L /proc/1/exe /out/docker-init.next; "
        "cp /usr/lib/frr/watchfrr.sh /out/watchfrr-original.sh.next; "
        "chmod 0755 /out/docker-init.next /out/watchfrr-original.sh.next; "
        "mv -f /out/docker-init.next /out/docker-init; "
        "mv -f /out/watchfrr-original.sh.next /out/watchfrr-original.sh",
    ])
    for filename, content in (("watchfrr-serial.sh", SERIAL_WRAPPER),
                              ("watchfrr-worker.sh", SERIAL_WORKER)):
        target = directory / filename
        target.write_text(content, encoding="utf-8")
        target.chmod(0o755)
    for node in topology["topology"]["nodes"].values():
        binds = node.setdefault("binds", [])
        for bind in (
            "./runtime/startup:/pc2-startup:ro",
            "./runtime/startup/watchfrr-serial.sh:/usr/lib/frr/watchfrr.sh:ro",
        ):
            if bind not in binds:
                binds.append(bind)
        node["entrypoint"] = "/pc2-startup/docker-init -- /usr/local/bin/start.sh"
    (directory / "image.json").write_text(
        json.dumps({"image": image, "id": metadata["Id"]}, indent=2) + "\n",
        encoding="utf-8",
    )
    print("OK: init y serialización FRR preparados; imagen original conservada")
