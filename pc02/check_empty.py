"""Comprueba y registra que los 30 FRR estén vacíos antes de configurar."""

from datetime import datetime
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import time

import yaml


def assert_empty(config, addresses, vrfs):
    """Rechaza protocolos, IP de datos, rutas estáticas y VRF preconfiguradas."""
    if "Current configuration:" not in config:
        raise ValueError("FRR no devolvió show running-config completo")
    forbidden = re.compile(
        r"^[ \t]*(?:router\s|mpls ldp\b|vrf\s|ip route\s|ipv6 route\s"
        r"|ip address\s|ipv6 address\s|ip ospf\s|ipv6 ospf6\s"
        r"|ip router\s|ipv6 router\s|neighbor\s|network\s)", re.MULTILINE,
    )
    if forbidden.search(config):
        raise ValueError("FRR ya tiene configuración de la práctica")
    if vrfs:
        raise ValueError("Ya existen VRF Linux antes de ejecutar Python")
    for interface in addresses:
        name = interface["ifname"]
        for address in interface.get("addr_info", []):
            ip = ipaddress.ip_address(address["local"])
            if name == "eth0" or (name == "lo" and ip.is_loopback):
                continue
            if ip.version == 6 and ip.is_link_local:
                continue
            raise ValueError(f"Dirección de datos previa: {name}: {ip}")


def inspect_node(host):
    """Consulta la configuración FRR y el estado Linux del contenedor."""
    sections = []
    values = []
    for command in (
        ["vtysh", "-c", "show running-config"],
        ["ip", "-j", "address", "show"],
        ["ip", "-j", "-d", "link", "show", "type", "vrf"],
    ):
        result = subprocess.run(
            ["docker", "exec", "-u", "0", host, *command],
            capture_output=True, text=True, timeout=30,
        )
        sections.append(f"=== {' '.join(command)} ===\n{result.stdout}{result.stderr}")
        if result.returncode:
            return sections, f"Consulta fallida: {' '.join(command)}"
        values.append(result.stdout)
    try:
        assert_empty(values[0], json.loads(values[1]), json.loads(values[2]))
    except (ValueError, KeyError, TypeError) as error:
        return sections, str(error)
    return sections, None


def main():
    """Conserva evidencia anterior a Python y exige 30 nodos sin rutas de datos."""
    base = Path(__file__).resolve().parent
    inventory = yaml.safe_load((base / "inventory.yml").read_text(encoding="utf-8"))
    nodes = inventory["nodes"]
    if len(nodes) != 30:
        raise SystemExit("FALLA: se esperaban 30 nodos")
    output = base / "logs" / "antes-python" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    output.mkdir(parents=True)
    passed = 0
    for name, node in nodes.items():
        sections = []
        error = "Consulta no completada"
        # Solo esperamos al arranque inicial de los daemons, sin reiniciarlos.
        for attempt in range(3):
            try:
                sections, error = inspect_node(node["host"])
            except (OSError, subprocess.TimeoutExpired) as failure:
                error = str(failure)
            if error is None or "ya tiene" in error or "previa" in error or "Ya existen" in error:
                break
            if attempt < 2:
                time.sleep(2)
        if error is None:
            passed += 1
            result = "OK: sin configuración de la práctica"
        else:
            result = f"FALLA: {error}"
        (output / f"log_{name}.txt").write_text(
            "\n".join(sections) + f"\nRESULTADO: {result}\n", encoding="utf-8",
        )
        if error is not None:
            print(f"{name}: {result}", flush=True)
    summary = f"Routers vacíos comprobados: {passed}/30\nRegistros: {output}\n"
    (output / "resumen.txt").write_text(summary, encoding="utf-8")
    if passed != 30:
        print(summary)
    raise SystemExit(0 if passed == 30 else 1)


if __name__ == "__main__":
    main()
