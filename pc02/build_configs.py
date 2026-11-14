"""Genera configuraciones FRR a partir del inventario y las bases del curso."""

import argparse
import ipaddress
import re
from pathlib import Path

import yaml


def remove_block(text, header):
    """Retira un bloque de nivel superior terminado en exit."""
    pattern = rf"^{re.escape(header)}\n.*?^exit[ \t]*\n"
    return re.sub(pattern, "", text, flags=re.MULTILINE | re.DOTALL)


def customer_addresses(customer, index):
    """Calcula las direcciones PE y CE del enlace de un sitio."""
    site = customer["sites"][index]
    transit = ipaddress.ip_network(site["transit"])
    lan = ipaddress.ip_interface(site["lan"])
    if transit.version != 4 or transit.prefixlen != 30:
        raise ValueError("Los enlaces de cliente deben ser IPv4 /30")
    return (
        f"{transit.network_address + 1}/{transit.prefixlen}",
        f"{transit.network_address + 2}/{transit.prefixlen}",
        lan,
    )


def site_config(name, node, customers):
    """Genera interfaces y OSPF para un sitio de cliente."""
    customer = customers[node["customer"]]
    _, ce_address, lan = customer_addresses(customer, node["index"])
    return f"""frr defaults traditional
hostname {name}
!
interface eth1
 ip address {ce_address}
 ip ospf area 0
 ip ospf network point-to-point
exit
!
interface lo
 ip address {lan}
 ip ospf area 0
 ip ospf passive
exit
!
router ospf
 ospf router-id {lan.ip}
exit
!
end
"""


def pe_config(text, node, customers):
    """Completa las dos VRF y sus anuncios VPN en un PE."""
    router_id = re.search(
        r"^ bgp router-id ([0-9.]+)$", text, re.MULTILINE
    )
    if not router_id:
        raise ValueError("La configuración base del PE no tiene router-id BGP")
    router_id = router_id.group(1)

    # Conservamos el método de activación OSPF de cada VRF base.
    network_customers = set()
    for customer_name in customers:
        block = re.search(
            rf"^router ospf vrf {re.escape(customer_name)}\n(.*?)^exit",
            text,
            re.MULTILINE | re.DOTALL,
        )
        if block and re.search(r"^ network ", block.group(1), re.MULTILINE):
            network_customers.add(customer_name)

    # Sustituimos los bloques del cliente A de la base por los generados.
    # Los bloques de transporte IGP, iBGP y LDP se conservan.
    for name, customer in customers.items():
        text = re.sub(
            rf"^vrf {re.escape(name)}\n.*?^exit-vrf[ \\t]*\n",
            "",
            text,
            flags=re.MULTILINE | re.DOTALL,
        )
        text = remove_block(
            text, f'interface {customer["pe_interface"]}'
        )
        text = remove_block(
            text, f'interface {customer["pe_interface"]} vrf {name}'
        )
        text = remove_block(text, f"router ospf vrf {name}")
        text = remove_block(
            text, f'router bgp {node["asn"]} vrf {name}'
        )

    additions = []
    for name, customer in customers.items():
        pe_address, _, _ = customer_addresses(customer, node["index"])
        pe_ip = ipaddress.ip_interface(pe_address).ip
        rt = f'{node["asn"]}:{customer["rt_suffix"]}'
        rd = f'{node["asn"]}:{node["index"] * 100 + customer["rt_suffix"]}'

        interface_area = (
            "" if name in network_customers else " ip ospf area 0\n"
        )
        network_area = (
            f' network {customer["sites"][node["index"]]["transit"]} area 0\n'
            if name in network_customers else ""
        )

        additions.append(f"""!
vrf {name}
exit-vrf
!
interface {customer["pe_interface"]} vrf {name}
 ip address {pe_address}
{interface_area} ip ospf network point-to-point
exit
!
router ospf vrf {name}
 ospf router-id {pe_ip}
 redistribute bgp
{network_area}exit
!
router bgp {node["asn"]} vrf {name}
 bgp router-id {router_id}
 address-family ipv4 unicast
  redistribute ospf
  label vpn export auto
  rd vpn export {rd}
  rt vpn both {rt}
  export vpn
  import vpn
 exit-address-family
exit
""")

    return text.rstrip() + "\n" + "".join(additions) + "!\nend\n"



def border_config(text, node):
    """Anuncia a los vecinos iBGP IPv4 un next-hop alcanzable por el IGP."""
    peers = re.findall(
        rf"^ neighbor ([0-9.]+) remote-as {node['asn']}[ \t]*$",
        text,
        re.MULTILINE,
    )
    if not peers:
        raise ValueError("El borde no tiene vecinos iBGP IPv4 en la base")

    commands = [
        f"router bgp {node['asn']}",
        " address-family ipv4 unicast",
    ]
    commands.extend(
        f"  neighbor {peer} next-hop-self" for peer in peers
    )
    commands.extend([" exit-address-family", "exit", "!"])
    return text.rstrip() + "\n!\n" + "\n".join(commands) + "\n"

def generate(inventory_path, output_dir):
    """Valida los datos y genera un archivo FRR por nodo."""
    data = yaml.safe_load(inventory_path.read_text(encoding="utf-8"))
    customers = data["customers"]
    results = {}

    for name, node in data["nodes"].items():
        if node["role"] == "site":
            text = site_config(name, node, customers)
        else:
            source = inventory_path.parent / node["base_config"]
            text = source.read_text(encoding="utf-8")
            text = re.sub(r"^end[ \t]*$", "", text, flags=re.MULTILINE)
            if node["role"] == "pe":
                text = pe_config(text, node, customers)
            elif node["role"] == "border":
                text = border_config(text, node) + "end\n"
            else:
                text = text.rstrip() + "\n!\nend\n"
        if node.get("test_address"):
            address = ipaddress.ip_interface(node["test_address"])
            if address.version != 4 or address.network.prefixlen != 32:
                raise ValueError("La dirección de prueba debe ser IPv4 /32")
            text = re.sub(r"^end[ \\t]*$", "", text, flags=re.MULTILINE)
            text = (
                text.rstrip()
                + f"\n!\ninterface lo\n ip address {address}\nexit\n!\nend\n"
            )
        results[name] = text

    # Guardamos solo después de generar correctamente todos los nodos.
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, text in results.items():
        path = output_dir / f"{name}.conf"
        path.write_text(text, encoding="utf-8")
        print(f"GENERADO: {path}")

    print(f"\nOK: {len(results)} configuraciones generadas; routers sin modificar")


def main():
    """Permite seleccionar inventario y directorio de salida."""
    base = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inventory", type=Path, default=base / "inventory.yml"
    )
    parser.add_argument(
        "--output", type=Path, default=base / "generated"
    )
    args = parser.parse_args()

    try:
        generate(args.inventory.resolve(), args.output.resolve())
    except (OSError, ValueError, KeyError, yaml.YAMLError) as error:
        parser.exit(1, f"FALLA: {error}\n")


if __name__ == "__main__":
    main()
