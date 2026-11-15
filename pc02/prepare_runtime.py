"""Prepara copias de ejecución sin modificar las configuraciones base."""

import shutil
from pathlib import Path

import yaml
from startup_support import prepare_startup


def prepare():
    """Copia las bases y genera la topología con montajes de ejecución."""
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
        mappings.append((name, node, matches[0], original, folder))

    runtime.mkdir()
    for name, node, old_bind, original, folder in mappings:
        destination = runtime / "configs" / folder.name
        shutil.copytree(
            folder,
            destination,
            ignore=shutil.ignore_patterns("*.sav"),
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
        node["exec"] = [permissions] + node.get("exec", [])
        print(f"PREPARADO: {name}")

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
