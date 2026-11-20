"""Prepara las VRF Linux de los PE durante la aplicación, nunca al desplegar."""

import json
import re
import subprocess


def docker_command(host, *args):
    """Ejecuta ip como root en el contenedor del inventario, sin usar shell."""
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", host):
        raise ValueError("Nombre de contenedor no válido")
    result = subprocess.run(
        ["docker", "exec", "-u", "0", host, *args],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode:
        raise RuntimeError(f"Preparación de VRF en {host}: {result.stderr or result.stdout}")
    return result.stdout


def prepare_linux_vrfs(node, customers):
    """Comprueba puertos/tablas y crea las VRF que va a configurar Netmiko."""
    host = node["host"]
    links = json.loads(docker_command(host, "ip", "-j", "-d", "link", "show"))
    by_name = {link["ifname"]: link for link in links}
    plans = []
    tables, interfaces = set(), set()
    for name, customer in customers.items():
        interface = customer["pe_interface"]
        table = int(customer["table"])
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", name):
            raise ValueError("Nombre de VRF no válido")
        if not re.fullmatch(r"eth[1-9][0-9]*", interface) or interface not in by_name:
            raise ValueError(f"Falta el puerto de cliente {interface}")
        if table <= 0 or table in (253, 254, 255) or table in tables:
            raise ValueError(f"Tabla VRF inválida o repetida: {table}")
        if interface in interfaces:
            raise ValueError(f"Puerto repetido: {interface}")
        tables.add(table)
        interfaces.add(interface)
        existing = by_name.get(name)
        if existing:
            info = existing.get("linkinfo", {})
            if info.get("info_kind") != "vrf" or info.get("info_data", {}).get("table") != table:
                raise ValueError(f"{name}: dispositivo o tabla existente incompatible")
        for link in links:
            info = link.get("linkinfo", {})
            if (info.get("info_kind") == "vrf"
                    and info.get("info_data", {}).get("table") == table
                    and link["ifname"] != name):
                raise ValueError(f"Tabla {table} ya utilizada por {link['ifname']}")
        master = by_name[interface].get("master")
        if master is not None and master not in (name, (existing or {}).get("ifindex")):
            raise ValueError(f"{interface}: ya pertenece a otra VRF o bridge")
        plans.append((name, table, interface, existing is None))

    # Todas las comprobaciones se completan antes de modificar enlaces.
    records = []
    for name, table, interface, missing in plans:
        if missing:
            docker_command(host, "ip", "link", "add", name, "type", "vrf", "table", str(table))
        docker_command(host, "ip", "link", "set", "dev", name, "up")
        docker_command(host, "ip", "link", "set", "dev", interface, "master", name)
        docker_command(host, "ip", "link", "set", "dev", interface, "up")
        records.append(f"{name}: tabla {table}; puerto {interface}")
    return "\n".join(records)
