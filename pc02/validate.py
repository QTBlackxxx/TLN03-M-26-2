"""Valida protocolos y conectividad de PC2 mediante SSH."""

import getpass
import ipaddress
import os
import re
import shlex
from pathlib import Path

import yaml
from netmiko import ConnectHandler

from run import execute


def expect(condition, description):
    """Convierte una comprobación incumplida en un error de validación."""
    if not condition:
        raise RuntimeError(description)


def transport_neighbors(name, topology, inventory):
    """Cuenta enlaces del nodo hacia routers de transporte del mismo AS."""
    count = 0
    for link in topology["topology"]["links"]:
        endpoints = [endpoint.split(":")[0] for endpoint in link["endpoints"]]
        if name not in endpoints:
            continue
        other = endpoints[1] if endpoints[0] == name else endpoints[0]
        peer = inventory["nodes"].get(other)
        if (
            peer
            and peer["asn"] == inventory["nodes"][name]["asn"]
            and peer["role"] != "site"
        ):
            count += 1
    return count


def expected_bgp_peers(config):
    """Obtiene vecinos activados en la familia IPv4 unicast global."""
    block = re.search(
        r"^router bgp \d+\n(.*?)^exit$",
        config,
        re.MULTILINE | re.DOTALL,
    )
    if not block:
        raise ValueError("Falta el bloque BGP global generado")
    return set(re.findall(
        r"^  neighbor ([0-9.]+) activate[ \t]*$",
        block.group(1),
        re.MULTILINE,
    ))


def validate_node(name, node, inventory, topology, password, base):
    """Ejecuta verificaciones por rol y conserva su evidencia."""
    sections = []
    defaults = inventory["defaults"]

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

            def show(command):
                """Consulta FRR, registra la salida y detecta comandos inválidos."""
                output = execute(
                    connection, f"vtysh -c {shlex.quote(command)}"
                )
                sections.append(f"=== {command} ===\n{output}\n")
                expect(
                    not any(error in output for error in (
                        "% Unknown command", "% Ambiguous command",
                        "% Command incomplete", "Exiting: failed to connect",
                    )),
                    f"FRR rechazó: {command}",
                )
                return output

            def ping(source, destination, should_work):
                """Comprueba ICMP distinguiendo pérdida de errores de ejecución."""
                command = (
                    f"ping -I {shlex.quote(source)} -c 2 -W 2 "
                    f"{shlex.quote(destination)}; "
                    'result=$?; printf "\\nPC2_PING=%s\\n" "$result"'
                )
                output = execute(connection, command)
                sections.append(
                    f"=== ping {source} -> {destination} ===\n{output}\n"
                )
                status = re.search(r"PC2_PING=(\d+)", output)
                expect(status is not None, "Ping sin código de resultado")
                expected = "0" if should_work else "1"
                expect(
                    status.group(1) == expected,
                    f"Resultado ICMP inesperado: {source} -> {destination}",
                )

            show("show version")
            show("show ip route")

            if node["role"] == "site":
                customer = inventory["customers"][node["customer"]]
                local = ipaddress.ip_interface(
                    customer["sites"][node["index"]]["lan"]
                )
                remote_index = 2 if node["index"] == 1 else 1
                remote = ipaddress.ip_interface(
                    customer["sites"][remote_index]["lan"]
                )

                ospf = show("show ip ospf neighbor")
                expect(
                    len(re.findall(r"\bFull/", ospf)) == 1,
                    "El sitio debe tener un vecino OSPF Full",
                )
                route = execute(
                    connection,
                    f"ip route get {remote.ip} from {local.ip}",
                )
                sections.append(f"=== ruta al sitio remoto ===\n{route}\n")
                expect("dev eth1" in route, "El sitio no sale por eth1")
                ping(str(local.ip), str(remote.ip), True)

                for other_name, other in inventory["customers"].items():
                    if other_name == node["customer"]:
                        continue
                    destination = ipaddress.ip_interface(
                        other["sites"][remote_index]["lan"]
                    )
                    ping(str(local.ip), str(destination.ip), False)

            else:
                expected = transport_neighbors(name, topology, inventory)
                if node["asn"] == 100:
                    output = show("show ip ospf neighbor")
                    actual = len(re.findall(r"\bFull/", output))
                else:
                    output = show("show isis neighbor")
                    actual = len(re.findall(
                        r"^[ \t]*\S+\s+eth\d+\s+2\s+Up\b",
                        output, re.MULTILINE,
                    ))
                expect(
                    actual == expected,
                    f"Vecinos IGP: {actual}; esperados: {expected}",
                )

                output = show("show mpls ldp neighbor")
                actual = len(re.findall(
                    r"^ipv4\s+\S+\s+OPERATIONAL\b",
                    output, re.MULTILINE,
                ))
                expect(
                    actual == expected,
                    f"Vecinos LDP: {actual}; esperados: {expected}",
                )

                config = (base / "generated" / f"{name}.conf").read_text(
                    encoding="utf-8"
                )
                peers = expected_bgp_peers(config)
                output = show("show bgp ipv4 unicast summary")
                established = set()
                for line in output.splitlines():
                    fields = line.split()
                    if (
                        len(fields) >= 10
                        and fields[0] in peers
                        and fields[9].isdigit()
                    ):
                        established.add(fields[0])
                expect(
                    established == peers,
                    f"BGP no establecido: {sorted(peers - established)}",
                )

                if node["role"] == "pe":
                    show("show bgp ipv4 vpn summary")
                    for customer_name, customer in inventory["customers"].items():
                        output = show(
                            f"show ip ospf vrf {customer_name} neighbor"
                        )
                        expect(
                            len(re.findall(r"\bFull/", output)) == 1,
                            f"Falta vecino OSPF en VRF {customer_name}",
                        )
                        routes = show(f"show ip route vrf {customer_name}")
                        remote_index = 2 if node["index"] == 1 else 1
                        remote = ipaddress.ip_interface(
                            customer["sites"][remote_index]["lan"]
                        )
                        expect(
                            re.search(
                                rf"^B[>* ]+\s*{re.escape(str(remote.ip))}/32\b",
                                routes, re.MULTILINE,
                            ) is not None,
                            f"Falta ruta VPN remota en {customer_name}",
                        )
                        for other_name, other in inventory["customers"].items():
                            if other_name == customer_name:
                                continue
                            for site in other["sites"].values():
                                address = ipaddress.ip_interface(site["lan"]).ip
                                expect(
                                    f"{address}/32" not in routes,
                                    f"Ruta del cliente {other_name} en {customer_name}",
                                )

                if node.get("test_address"):
                    local = ipaddress.ip_interface(node["test_address"]).ip
                    for peer in inventory["nodes"].values():
                        if peer["asn"] == node["asn"] or not peer.get("test_address"):
                            continue
                        destination = ipaddress.ip_interface(
                            peer["test_address"]
                        ).ip
                        route = execute(
                            connection,
                            f"ip route get {destination} from {local}",
                        )
                        sections.append(f"=== ruta entre AS ===\n{route}\n")
                        expect(
                            "dev eth0" not in route,
                            "El tráfico entre AS utiliza gestión",
                        )
                        ping(str(local), str(destination), True)

        sections.append("RESULTADO: OK\n")
        print(f"OK: {name}")
        return True

    except Exception as error:
        sections.append(f"RESULTADO: FALLA: {type(error).__name__}: {error}\n")
        print(f"FALLA: {name}: {error}")
        return False
    finally:
        (base / "logs" / "validacion" / f"log_{name}.txt").write_text(
            "\n".join(sections), encoding="utf-8"
        )


def main():
    """Carga los datos, valida todos los nodos y resume resultados."""
    base = Path(__file__).resolve().parent
    inventory = yaml.safe_load(
        (base / "inventory.yml").read_text(encoding="utf-8")
    )
    topology = yaml.safe_load(
        (base / "escenario02.yml").read_text(encoding="utf-8")
    )
    password = os.getenv(
        inventory["defaults"]["password_env"]
    ) or getpass.getpass("Contraseña SSH del laboratorio: ")

    directory = base / "logs" / "validacion"
    directory.mkdir(parents=True, exist_ok=True)

    results = [
        validate_node(name, node, inventory, topology, password, base)
        for name, node in inventory["nodes"].items()
    ]
    summary = f"Nodos validados: {sum(results)}/{len(results)}"
    (directory / "resumen.txt").write_text(summary + "\n", encoding="utf-8")
    print(f"\n{summary}")
    raise SystemExit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
