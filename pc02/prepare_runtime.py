"""Prepara FRR sin configuración de la práctica; conserva las bases originales."""

import re
import shutil
from pathlib import Path

import yaml
from startup_support import prepare_startup


def prepare():
    """Crea configuración mínima y traslada las VRF Linux a la fase de aplicación."""
    base = Path(__file__).resolve().parent
    runtime = base / "runtime"
    source = base / "escenario02.yml"
    topology = yaml.safe_load(source.read_text(encoding="utf-8"))

    if runtime.exists():
        raise RuntimeError(
            "runtime ya existe. Se conserva para no sobrescribir "
            "configuraciones guardadas."
        )

    # Validamos los montajes antes de crear archivos.
    mappings = []
    for name, node in topology["topology"]["nodes"].items():
        matches = [
            bind for bind in node.get("binds", [])
            if bind.split(":")[1] == "/etc/frr"
        ]
        if len(matches) != 1:
            raise ValueError(f"{name}: se esperaba un montaje /etc/frr")
        original = Path(matches[0].split(":")[0])
        folder = (base / original).resolve()
        if not folder.is_dir():
            raise ValueError(f"{name}: falta {folder}")
        if not (folder / "daemons").is_file():
            raise ValueError(f"{name}: falta el archivo daemons")
        mappings.append((name, node, matches[0], original, folder))

    runtime.mkdir()
    for name, node, old_bind, original, folder in mappings:
        destination = runtime / "configs" / folder.name
        # Solo habilitamos los procesos. Ningún .conf de las bases se monta.
        destination.mkdir(parents=True)
        shutil.copy2(folder / "daemons", destination / "daemons")
        (destination / "frr.conf").write_text(
            f"frr defaults traditional\nhostname {name}\n"
            "service integrated-vtysh-config\n!\nend\n",
            encoding="utf-8",
        )
        (destination / "vtysh.conf").write_text(
            "service integrated-vtysh-config\n", encoding="utf-8"
        )

        new_bind = f"./runtime/configs/{folder.name}:/etc/frr"
        node["binds"] = [
            new_bind if bind == old_bind else bind
            for bind in node["binds"]
        ]

        # Containerlab ejecuta esta preparación como root.
        # La aplicación de configuración seguirá por SSH con admin.
        permissions = (
            'bash -c "chown -R frr:frr /etc/frr '
            '&& chmod -R u+rwX,go+rX /etc/frr"'
        )
        # Las VRF y asociaciones de puertos las crea run.py al configurar.
        vrf_command = re.compile(
            r'^bash -c "ip link (?:add [AB] type vrf table (?:10|20)'
            r'|set [AB] up|set eth[34] master [AB])"$'
        )
        node["exec"] = [permissions] + [
            cmd for cmd in node.get("exec", [])
            if not vrf_command.fullmatch(cmd)
        ]
        print(f"PREPARADO SIN CONFIGURACIÓN DE RED: {name}")

    prepare_startup(base, topology)

    target = base / "escenario02.runtime.yml"
    target.write_text(
        yaml.safe_dump(topology, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"OK: topología de ejecución: {target}")


if __name__ == "__main__":
    try:
        prepare()
    except (OSError, ValueError, RuntimeError, yaml.YAMLError) as error:
        raise SystemExit(f"FALLA: {error}")
