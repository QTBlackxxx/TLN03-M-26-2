"""Aplica configuraciones FRR por SSH y guarda verificaciones por nodo."""

import argparse
import getpass
import os
import re
import shlex
import uuid
from pathlib import Path

import yaml
from netmiko import ConnectHandler
from build_configs import generate


def execute(connection, command):
    """Ejecuta un comando y comprueba su código de salida remoto."""
    marker = f"PC2_STATUS_{uuid.uuid4().hex}"
    wrapped = f"{command}; printf '\\n{marker}=%s\\n' \"$?\""
    output = connection.send_command(wrapped, read_timeout=120)
    match = re.search(rf"{marker}=(\d+)", output)
    if not match:
        raise RuntimeError("No se recibió el estado del comando remoto")
    result = output[:match.start()].rstrip()
    if match.group(1) != "0":
        raise RuntimeError(f"Comando remoto fallido:\n{result}")
    return result


def apply_node(name, node, defaults, password, base, log_dir):
    """Transfiere, aplica, guarda y consulta la configuración de un nodo."""
    sections = []
    remote_path = f"/tmp/pc2-{uuid.uuid4().hex}.conf"
    try:
        config = (base / "generated" / f"{name}.conf").read_text(
            encoding="utf-8"
        )
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
            # SFTP utiliza la misma sesión SSH autenticada de Netmiko.
            with connection.remote_conn_pre.open_sftp() as sftp:
                with sftp.file(remote_path, "w") as remote_file:
                    remote_file.write(config)

            try:
                applied = execute(
                    connection, f"vtysh -f {shlex.quote(remote_path)}"
                )
                sections.append(f"=== APLICACIÓN ===\n{applied}\n")

                errors = (
                    "% Unknown command", "% Ambiguous command",
                    "% Command incomplete", "Failure to communicate",
                    "Exiting: failed to connect",
                )
                if any(error in applied for error in errors):
                    raise RuntimeError("FRR informó un error; consultar el log")

                saved = execute(connection, 'vtysh -c "write memory"')
                sections.append(f"=== WRITE MEMORY ===\n{saved}\n")
                save_errors = (
                    "Can't open configuration file",
                    "Permission denied",
                    "Failed to",
                    "failed to",
                    "Error writing",
                    "error writing",
                )
                # El aviso conocido de vtysh.conf ausente se trata aparte.
                save_lines = [
                    line for line in saved.splitlines()
                    if "/etc/frr/vtysh.conf" not in line
                ]
                if any(
                    error in line
                    for line in save_lines
                    for error in save_errors
                ):
                    raise RuntimeError("Guardado incompleto; consultar el log")
                if "[OK]" not in saved and "Configuration saved" not in saved:
                    raise RuntimeError(
                        "No se confirmó el guardado; consultar el log"
                    )

                for command in (
                    "show running-config",
                    "show ip route",
                    "show ip ospf neighbor",
                ):
                    output = execute(
                        connection, f"vtysh -c {shlex.quote(command)}"
                    )
                    sections.append(f"=== {command} ===\n{output}\n")
            finally:
                connection.send_command(
                    f"rm -f {shlex.quote(remote_path)}",
                    read_timeout=10,
                )

        print(f"OK: {name}: aplicado, guardado y consultado")
        return True

    except Exception as error:
        sections.append(f"ERROR: {type(error).__name__}: {error}\n")
        print(f"FALLA: {name}: {error}")
        return False
    finally:
        (log_dir / f"log_{name}.txt").write_text(
            "\n".join(sections), encoding="utf-8"
        )


def main():
    """Selecciona nodos del inventario y aplica sus archivos generados."""
    base = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--method", choices=["netmiko"], default="netmiko")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--nodes", nargs="+")
    selection.add_argument("--all", action="store_true")
    args = parser.parse_args()

    inventory = yaml.safe_load(
        (base / "inventory.yml").read_text(encoding="utf-8")
    )
    if args.all:
        order = {"core": 0, "rr": 1, "border": 2, "pe": 3, "site": 4}
        args.nodes = sorted(
            inventory["nodes"],
            key=lambda name: (
                order[inventory["nodes"][name]["role"]],
                inventory["nodes"][name]["asn"],
                name,
            ),
        )

    generate(base / "inventory.yml", base / "generated")

    for name in args.nodes:
        if name not in inventory["nodes"]:
            parser.error(f"Nodo fuera del inventario: {name}")
        if not (base / "generated" / f"{name}.conf").is_file():
            parser.error(f"Falta configuración generada para {name}")

    defaults = inventory["defaults"]
    password = os.getenv(defaults["password_env"]) or getpass.getpass(
        "Contraseña SSH del laboratorio: "
    )
    log_dir = base / "logs" / "aplicacion"
    log_dir.mkdir(parents=True, exist_ok=True)

    results = [
        apply_node(
            name, inventory["nodes"][name], defaults,
            password, base, log_dir,
        )
        for name in args.nodes
    ]
    print(f"\nAplicaciones confirmadas: {sum(results)}/{len(results)}")
    raise SystemExit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
