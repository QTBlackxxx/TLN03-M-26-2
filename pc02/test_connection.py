"""Comprueba el acceso SSH de solo lectura a un nodo del inventario."""

import getpass
import os
from pathlib import Path

import yaml
from netmiko import ConnectHandler


def main():
    inventory_path = Path(__file__).with_name("inventory.yml")
    inventory = yaml.safe_load(inventory_path.read_text(encoding="utf-8"))

    name = "as100-p2"
    defaults = inventory["defaults"]
    node = inventory["nodes"][name]
    password = os.getenv(defaults["password_env"]) or getpass.getpass(
        f"Contraseña SSH para {defaults['username']}: "
    )

    print(f"Conectando a {name} ({node['host']})...")
    with ConnectHandler(
        device_type="linux",
        host=node["host"],
        username=defaults["username"],
        password=password,
        port=defaults["port"],
        conn_timeout=10,
        auth_timeout=10,
    ) as connection:
        output = connection.send_command(
            'vtysh -c "show ip ospf neighbor"',
            read_timeout=20,
        )

    print(output)
    if "Full/" not in output:
        raise SystemExit("FALLA: no se encontró una vecindad OSPF Full")
    print("OK: inventario, credenciales, Netmiko y vtysh funcionan")


if __name__ == "__main__":
    main()
