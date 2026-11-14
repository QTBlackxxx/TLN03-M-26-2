"""Verifica acceso SSH y guarda el estado inicial de todos los nodos."""

import getpass
import os
from pathlib import Path

import yaml
from netmiko import ConnectHandler


def check_node(name, node, defaults, password, output_dir):
    """Consulta un nodo sin modificar su configuración y guarda evidencias."""
    log_path = output_dir / f"log_{name}.txt"
    sections = []

    try:
        with ConnectHandler(
            device_type="linux",
            host=node["host"],
            username=defaults["username"],
            password=password,
            port=defaults.get("port", 22),
            conn_timeout=10,
            auth_timeout=15,
            banner_timeout=20,
        ) as connection:
            for command in ("show version", "show running-config"):
                output = connection.send_command(
                    f'vtysh -c "{command}"',
                    read_timeout=30,
                )
                sections.append(f"=== {command} ===\n{output}\n")
                if "Exiting: failed to connect" in output:
                    raise RuntimeError("vtysh no puede acceder a los procesos FRR")

        log_path.write_text("\n".join(sections), encoding="utf-8")
        print(f"OK: {name}")
        return True

    except Exception as error:
        sections.append(f"ERROR: {type(error).__name__}: {error}\n")
        log_path.write_text("\n".join(sections), encoding="utf-8")
        print(f"FALLA: {name}: {type(error).__name__}")
        return False


def main():
    """Carga el inventario, solicita la contraseña y resume los resultados."""
    base = Path(__file__).resolve().parent
    inventory = yaml.safe_load(
        (base / "inventory.yml").read_text(encoding="utf-8")
    )
    defaults = inventory["defaults"]
    password = os.getenv(defaults["password_env"]) or getpass.getpass(
        "Contraseña SSH del laboratorio: "
    )
    output_dir = base / "logs" / "estado-inicial"
    output_dir.mkdir(parents=True, exist_ok=True)

    results = [
        check_node(name, node, defaults, password, output_dir)
        for name, node in inventory["nodes"].items()
    ]

    passed = sum(results)
    print(f"\nAccesos correctos: {passed}/{len(results)}")
    print(f"Registros: {output_dir}")
    raise SystemExit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
