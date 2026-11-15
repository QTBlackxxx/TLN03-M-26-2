"""Pruebas secuenciales de fallas individuales para PC2.

Cada caso restaura sus interfaces antes del siguiente. Un router se simula
aislando sus puertos de datos, conservando eth0 y su proceso Linux.
No modifica FRR ni ejecuta write memory. No certifica fallas simultáneas.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime
import csv
import getpass
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time

import yaml


@dataclass(frozen=True)
class Case:
    """Una falla de enlace o el aislamiento de un nodo."""

    name: str
    kind: str
    node: str
    ports: tuple


@dataclass(frozen=True)
class Probe:
    """Flujo con IP de origen explícita."""

    name: str
    node: str
    source: str
    destination: str


def command(args, timeout=20):
    """Ejecuta argumentos sin shell y conserva salida y retorno."""
    return subprocess.run(
        args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )


def checked(args, timeout=20):
    """Rechaza errores del comando solicitado."""
    result = command(args, timeout)
    if result.returncode:
        raise RuntimeError(
            f"Comando fallido: {args!r}\n{result.stdout}"
        )
    return result.stdout


def atomic_json(path, data):
    """Escribe un archivo JSON mediante reemplazo atómico."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def catalog(topology, inventory):
    """Obtiene los enlaces y puertos de datos de cada nodo."""
    ports = {name: set() for name in inventory["nodes"]}
    links = []

    for link in topology["topology"]["links"]:
        endpoints = [
            endpoint.rsplit(":", 1)
            for endpoint in link["endpoints"]
        ]

        if len(endpoints) != 2:
            raise ValueError(
                "Solo se admiten enlaces de dos extremos"
            )

        for name, interface in endpoints:
            if (
                name not in ports
                or not re.fullmatch(
                    r"eth[1-9][0-9]*", interface
                )
            ):
                raise ValueError(
                    f"Extremo no reconocido: {name}:{interface}"
                )
            ports[name].add(interface)

        name, interface = endpoints[0]
        links.append(
            Case(
                f"link-{name}-{interface}",
                "enlace",
                name,
                (interface,),
            )
        )

    routers = [
        Case(
            f"node-{name}",
            "aislamiento",
            name,
            tuple(sorted(interfaces)),
        )
        for name, interfaces in ports.items()
    ]

    return links, routers


def select_cases(topology, inventory, suite, only):
    """Selecciona los casos solicitados."""
    links, routers = catalog(topology, inventory)
    all_cases = {
        case.name: case
        for case in links + routers
    }

    if only:
        unknown = set(only) - all_cases.keys()
        if unknown:
            raise ValueError(
                f"Casos no reconocidos: {sorted(unknown)}"
            )
        return [
            all_cases[name]
            for name in dict.fromkeys(only)
        ]

    if suite == "all":
        return links + routers

    if suite == "transport":
        good_roles = {"core", "rr", "pe"}
        selected = []

        for link, case in zip(
            topology["topology"]["links"], links
        ):
            peers = [
                inventory["nodes"][e.rsplit(":", 1)[0]]
                for e in link["endpoints"]
            ]

            if (
                all(
                    node["role"] in good_roles
                    for node in peers
                )
                and peers[0]["asn"] == peers[1]["asn"]
            ):
                selected.append(case)

        selected.extend(
            case
            for case in routers
            if inventory["nodes"][case.node]["role"]
            in {"core", "rr"}
        )
        return selected

    selected = []

    for asn in sorted({
        node["asn"]
        for node in inventory["nodes"].values()
    }):
        names = (
            f"link-as{asn}-pe1-eth2",
            f"node-as{asn}-p5",
            f"link-as{asn}-pe2-eth1",
            f"link-as{asn}-p2-eth2",
        )
        selected.extend(
            all_cases[name] for name in names
        )

    return selected


def make_probes(inventory):
    """Genera flujos VPN y entre proveedores en ambos sentidos."""
    nodes = inventory["nodes"]
    probes = []

    for name, node in nodes.items():
        if node["role"] == "site":
            sites = inventory["customers"][
                node["customer"]
            ]["sites"]

            source = str(
                ipaddress.ip_interface(
                    sites[node["index"]]["lan"]
                ).ip
            )
            destination = str(
                ipaddress.ip_interface(
                    sites[3 - node["index"]]["lan"]
                ).ip
            )

            probes.append(
                Probe(
                    f"VPN-{name}",
                    name,
                    source,
                    destination,
                )
            )

        elif node.get("test_address"):
            for peer in nodes.values():
                if (
                    peer.get("test_address")
                    and peer["asn"] != node["asn"]
                ):
                    probes.append(
                        Probe(
                            f"inter-AS-{name}",
                            name,
                            str(
                                ipaddress.ip_interface(
                                    node["test_address"]
                                ).ip
                            ),
                            str(
                                ipaddress.ip_interface(
                                    peer["test_address"]
                                ).ip
                            ),
                        )
                    )

    if not probes:
        raise ValueError(
            "No se generaron flujos de prueba"
        )

    return probes


class Runner:
    """Controla fallas, evidencias y recuperación."""

    def __init__(
        self, base, topology, inventory, output, args
    ):
        self.base = base
        self.inventory = inventory
        self.output = output
        self.args = args
        self.lab = topology["name"]
        self.probes = make_probes(inventory)
        self.pending = output / "pending_restore.json"
        self.events = output / "muestras.jsonl"
        self.rows = []
        self.password = None

        self.pool = ThreadPoolExecutor(
            max_workers=min(10, len(self.probes))
        )

    def container(self, node):
        """Construye el nombre del contenedor."""
        return f"clab-{self.lab}-{node}"

    def docker(self, node, *args):
        """Construye un comando dentro del contenedor."""
        return [
            "docker",
            "exec",
            "-u",
            "0",
            self.container(node),
            *args,
        ]

    def record(self, kind, **data):
        """Registra resultados sin credenciales."""
        entry = {
            "time": datetime.now().astimezone().isoformat(),
            "kind": kind,
            **data,
        }
        with self.events.open(
            "a", encoding="utf-8"
        ) as stream:
            stream.write(
                json.dumps(entry, ensure_ascii=False)
                + "\n"
            )

    def preflight(self):
        """Exige todos los contenedores activos."""
        for name in self.inventory["nodes"]:
            status = json.loads(
                checked([
                    "docker",
                    "inspect",
                    self.container(name),
                ])
            )[0]

            if not status["State"]["Running"]:
                raise RuntimeError(
                    f"Contenedor detenido: {name}"
                )

    def probe(self, probe):
        """Comprueba la ruta de datos e ICMP."""
        try:
            route = command(
                self.docker(
                    probe.node,
                    "ip",
                    "-4",
                    "route",
                    "get",
                    probe.destination,
                    "from",
                    probe.source,
                ),
                timeout=12,
            )

            if (
                route.returncode
                or not re.search(
                    r"\bdev eth[1-9][0-9]*\b",
                    route.stdout,
                )
            ):
                return {
                    "flow": probe.name,
                    "ok": False,
                    "detail": route.stdout,
                    "reason": "sin ruta de datos válida",
                }

            ping = command(
                self.docker(
                    probe.node,
                    "ping",
                    "-n",
                    "-I",
                    probe.source,
                    "-c",
                    "1",
                    "-W",
                    "1",
                    "-w",
                    "2",
                    probe.destination,
                ),
                timeout=12,
            )

            return {
                "flow": probe.name,
                "ok": ping.returncode == 0,
                "route": route.stdout,
                "detail": ping.stdout,
                "returncode": ping.returncode,
            }

        except (
            OSError,
            subprocess.TimeoutExpired,
        ) as error:
            return {
                "flow": probe.name,
                "ok": False,
                "reason": str(error),
            }

    def sample(self, phase, case):
        """Ejecuta una ronda de flujos en paralelo."""
        results = list(
            self.pool.map(self.probe, self.probes)
        )
        self.record(
            "round",
            phase=phase,
            case=case,
            results=results,
        )
        return results

    def wait_healthy(self, phase, case):
        """Exige tres rondas correctas consecutivas."""
        deadline = (
            time.monotonic()
            + self.args.recovery_timeout
        )
        streak = 0

        while time.monotonic() < deadline:
            results = self.sample(phase, case)

            if all(result["ok"] for result in results):
                streak += 1
            else:
                streak = 0

            passed = sum(
                result["ok"] for result in results
            )

            print(
                f"  {phase}: {passed}/{len(results)} "
                f"flujos; estabilidad {streak}/3",
                flush=True,
            )

            if streak >= 3:
                return

            time.sleep(self.args.interval)

        raise RuntimeError(
            f"No se recuperó la comunicación: {phase}. "
            "No se prueba otro caso."
        )

    def validate(self, label):
        """Exige validación completa y reintenta protocolos en recuperación."""
        variable = self.inventory["defaults"]["password_env"]

        if self.password is None:
            self.password = os.getenv(variable) or getpass.getpass(
                "Contraseña SSH del laboratorio: "
            )

        environment = dict(os.environ)
        environment[variable] = self.password
        count = len(self.inventory["nodes"])
        attempts = 1 if label == "inicial" else 3

        markers = (
            "Vecinos IGP:",
            "Vecinos LDP:",
            "BGP no establecido:",
            "Falta vecino OSPF",
            "Falta ruta VPN remota",
        )

        if label != "inicial":
            print(
                "  Esperando 20 segundos para recuperar protocolos...",
                flush=True,
            )
            time.sleep(20)

        for attempt in range(1, attempts + 1):
            print(
                f"  Validación completa: {label}; "
                f"intento {attempt}/{attempts}",
                flush=True,
            )

            path = (
                self.output
                / f"validacion-{label}-intento-{attempt}.txt"
            )

            with path.open("w", encoding="utf-8") as stream:
                result = subprocess.run(
                    [sys.executable, str(self.base / "validate.py")],
                    env=environment,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=1200,
                    check=False,
                )

            text = path.read_text(encoding="utf-8")

            (self.output / f"validacion-{label}.txt").write_text(
                text, encoding="utf-8"
            )

            failures = [
                line for line in text.splitlines()
                if line.startswith("FALLA:")
            ]

            if (
                result.returncode == 0
                and not failures
                and f"Nodos validados: {count}/{count}" in text
            ):
                print(f"  OK: {count}/{count}", flush=True)
                return

            for line in failures:
                print(f"  {line}", flush=True)

            transient = bool(failures) and all(
                any(marker in line for marker in markers)
                for line in failures
            )

            if attempt == attempts or not transient:
                raise RuntimeError(
                    f"Validación incompleta. Revisar {path}. "
                    "Se detiene la secuencia."
                )

            print(
                "  Vecindades todavía incompletas. "
                "Reintento en 20 segundos; se exige 30/30.",
                flush=True,
            )
            time.sleep(20)

    def snapshot(self, case, phase):
        """Guarda rutas y resúmenes BGP de los PE."""
        path = (
            self.output
            / f"{case.name}-{phase}.txt"
        )

        commands = (
            "show ip route vrf A",
            "show ip route vrf B",
            "show bgp ipv4 unicast summary",
            "show bgp ipv4 vpn summary",
        )

        with path.open(
            "w", encoding="utf-8"
        ) as stream:
            for name, node in self.inventory[
                "nodes"
            ].items():
                if node["role"] != "pe":
                    continue

                for show in commands:
                    stream.write(
                        f"\n=== {name}: {show} ===\n"
                    )

                    try:
                        result = command(
                            self.docker(
                                name,
                                "vtysh",
                                "-c",
                                show,
                            )
                        )
                        stream.write(result.stdout)

                    except subprocess.TimeoutExpired:
                        stream.write(
                            "Consulta agotó su tiempo "
                            "de espera\n"
                        )

    def arm(self, case):
        """Registra la recuperación antes de apagar puertos."""
        status = json.loads(
            checked([
                "docker",
                "inspect",
                self.container(case.node),
            ])
        )[0]

        if not status["State"]["Running"]:
            raise RuntimeError(
                f"Nodo detenido: {case.node}"
            )

        targets = []

        for port in case.ports:
            info = json.loads(
                checked(
                    self.docker(
                        case.node,
                        "ip",
                        "-j",
                        "link",
                        "show",
                        "dev",
                        port,
                    )
                )
            )[0]

            if "UP" not in info["flags"]:
                raise RuntimeError(
                    f"{case.node}:{port} ya estaba "
                    "apagado; se cancela el caso."
                )

            targets.append({
                "container": self.container(case.node),
                "id": status["Id"],
                "port": port,
            })

        atomic_json(
            self.pending,
            {
                "hostname": socket.gethostname(),
                "case": case.name,
                "targets": targets,
            },
        )

        for target in targets:
            checked(
                self.docker(
                    case.node,
                    "ip",
                    "link",
                    "set",
                    "dev",
                    target["port"],
                    "down",
                )
            )

        self.record(
            "fault_active",
            case=asdict(case),
        )

    def case(self, case):
        """Prueba una falla y restaura aunque haya errores."""
        print(
            f"\n=== {case.name}: {case.kind}; "
            f"{case.ports} ===",
            flush=True,
        )

        self.wait_healthy("antes", case.name)
        self.snapshot(case, "antes")

        role = self.inventory[
            "nodes"
        ][case.node]["role"]

        hold = max(
            self.args.hold_seconds,
            210 if role == "rr" else 0,
        )

        row = {
            "case": case.name,
            "kind": case.kind,
            "hold_seconds": hold,
            "result": "INTERRUMPIDO",
            "stable_block_seconds": None,
            "failed_at_end": [],
            "recovery": "PENDIENTE",
        }

        self.rows.append(row)
        self.save_summary()

        try:
            self.arm(case)

            started = time.monotonic()
            streak = 0
            recent = []

            while True:
                results = self.sample(
                    "falla", case.name
                )
                elapsed = (
                    time.monotonic() - started
                )

                if all(r["ok"] for r in results):
                    streak += 1
                else:
                    streak = 0

                recent.append(results)
                recent = recent[-3:]

                if (
                    streak >= 3
                    and row["stable_block_seconds"]
                    is None
                ):
                    row["stable_block_seconds"] = round(
                        elapsed, 2
                    )

                passed = sum(
                    r["ok"] for r in results
                )

                print(
                    f"  FALLA ACTIVA "
                    f"{elapsed:.0f}/{hold}s: "
                    f"{passed}/{len(results)} flujos",
                    flush=True,
                )

                if (
                    elapsed >= hold
                    and len(recent) == 3
                ):
                    break

                time.sleep(self.args.interval)

            failures = sorted({
                result["flow"]
                for sample in recent
                for result in sample
                if not result["ok"]
            })

            row["failed_at_end"] = failures
            row["result"] = (
                "NO_TOLERADO"
                if failures
                else "TOLERADO"
            )

            self.snapshot(case, "durante")

        except BaseException as error:
            row["error"] = (
                f"{type(error).__name__}: {error}"
            )
            raise

        finally:
            previous = {
                sig: signal.signal(
                    sig, signal.SIG_IGN
                )
                for sig in (
                    signal.SIGINT,
                    signal.SIGTERM,
                )
            }

            try:
                restore(self.pending)
            finally:
                for sig, handler in previous.items():
                    signal.signal(sig, handler)
                self.save_summary()

        self.wait_healthy(
            "recuperación", case.name
        )
        self.validate(case.name)

        row["recovery"] = "OK"
        self.snapshot(case, "despues")
        self.save_summary()

        print(
            f"  RESULTADO: {row['result']}; "
            "recuperación completa OK",
            flush=True,
        )

    def save_summary(self):
        """Guarda el resumen incremental."""
        atomic_json(
            self.output / "resumen.json",
            self.rows,
        )

        with (
            self.output / "resumen.csv"
        ).open(
            "w",
            encoding="utf-8",
            newline="",
        ) as stream:
            writer = csv.writer(stream)

            writer.writerow([
                "caso",
                "tipo",
                "resultado",
                "observacion_segundos",
                "primer_bloque_3_rondas_segundos",
                "flujos_fallidos_finales",
                "recuperacion",
            ])

            for row in self.rows:
                writer.writerow([
                    row["case"],
                    row["kind"],
                    row["result"],
                    row["hold_seconds"],
                    row["stable_block_seconds"],
                    "; ".join(
                        row["failed_at_end"]
                    ),
                    row["recovery"],
                ])


def restore(path):
    """Restaura puertos del mismo contenedor original."""
    if not path.exists():
        return

    state = json.loads(
        path.read_text(encoding="utf-8")
    )

    if state["hostname"] != socket.gethostname():
        raise RuntimeError(
            "El diario corresponde a otra máquina"
        )

    remaining = []

    for target in state["targets"]:
        try:
            status = json.loads(
                checked([
                    "docker",
                    "inspect",
                    target["container"],
                ])
            )[0]

            if status["Id"] != target["id"]:
                raise RuntimeError(
                    "El contenedor fue sustituido; "
                    "revisar manualmente."
                )

            args = [
                "docker",
                "exec",
                "-u",
                "0",
                target["container"],
            ]

            checked(
                args + [
                    "ip",
                    "link",
                    "set",
                    "dev",
                    target["port"],
                    "up",
                ]
            )

            info = json.loads(
                checked(
                    args + [
                        "ip",
                        "-j",
                        "link",
                        "show",
                        "dev",
                        target["port"],
                    ]
                )
            )[0]

            if "UP" not in info["flags"]:
                raise RuntimeError(
                    "El puerto no volvió a UP"
                )

            print(
                "  RESTAURADO: "
                f"{target['container']}:"
                f"{target['port']}",
                flush=True,
            )

        except (
            RuntimeError,
            OSError,
            subprocess.TimeoutExpired,
        ) as error:
            print(
                f"  RECUPERACIÓN PENDIENTE: "
                f"{target}: {error}",
                flush=True,
            )
            remaining.append(target)

    if remaining:
        state["targets"] = remaining
        atomic_json(path, state)

        raise RuntimeError(
            "Quedan puertos por recuperar. "
            f"Ejecutar --restore {path}"
        )

    path.unlink()


def main():
    """Muestra el plan o ejecuta las pruebas solicitadas."""
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "--suite",
        choices=("demo", "transport", "all"),
        default="demo",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        help="Identificadores exactos del listado",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
    )
    parser.add_argument(
        "--restore",
        type=Path,
        help="Recuperar un pending_restore.json",
    )
    parser.add_argument(
        "--hold-seconds",
        type=int,
        default=75,
    )
    parser.add_argument(
        "--recovery-timeout",
        type=int,
        default=150,
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=2,
    )

    args = parser.parse_args()

    if args.restore:
        if not args.restore.is_file():
            raise ValueError(
                "No existe el diario de recuperación: "
                f"{args.restore}"
            )
        restore(args.restore.resolve())
        return 0

    if (
        args.hold_seconds < 30
        or args.recovery_timeout < 15
        or args.interval < 1
    ):
        parser.error(
            "Usar hold >=30, "
            "recovery-timeout >=15 e interval >=1"
        )

    base = Path(__file__).resolve().parent

    topology = yaml.safe_load(
        (base / "escenario02.yml").read_text(
            encoding="utf-8"
        )
    )
    inventory = yaml.safe_load(
        (base / "inventory.yml").read_text(
            encoding="utf-8"
        )
    )

    if set(
        topology["topology"]["nodes"]
    ) != set(inventory["nodes"]):
        raise ValueError(
            "Los nodos del inventario y "
            "la topología no coinciden"
        )

    cases = select_cases(
        topology,
        inventory,
        args.suite,
        args.only,
    )

    for index, case in enumerate(cases, 1):
        print(
            f"{index:02d}. {case.name}: "
            f"{case.node} -> "
            f"{', '.join(case.ports)}"
        )

    print(
        f"\nCasos: {len(cases)}. "
        "Flujos por ronda: "
        f"{len(make_probes(inventory))}."
    )
    print(
        "Un solo caso activo cada vez. "
        "Aislar un nodo no equivale "
        "a apagar su contenedor."
    )

    if not args.execute:
        print(
            "Solo listado; añadir --execute "
            "para ejecutar el plan."
        )
        return 0

    pending = list(
        (
            base / "logs" / "fallas-auto"
        ).glob("*/pending_restore.json")
    )

    if pending:
        raise RuntimeError(
            "Hay recuperación pendiente: "
            f"{pending[0]}. Usar --restore "
            "antes de continuar."
        )

    if not (
        base / "validate.py"
    ).is_file():
        raise ValueError("Falta validate.py")

    output = (
        base
        / "logs"
        / "fallas-auto"
        / datetime.now().strftime(
            "%Y%m%d-%H%M%S-%f"
        )
    )
    output.mkdir(parents=True)

    atomic_json(
        output / "plan.json",
        {
            "suite": args.suite,
            "cases": [
                asdict(case) for case in cases
            ],
            "probes": [
                asdict(probe)
                for probe in make_probes(inventory)
            ],
            "args": {
                key: (
                    str(value)
                    if isinstance(value, Path)
                    else value
                )
                for key, value
                in vars(args).items()
            },
        },
    )

    print(
        f"EVIDENCIAS: {output}",
        flush=True,
    )

    def interrupted(signum, frame):
        raise KeyboardInterrupt(
            f"Señal {signum}"
        )

    signal.signal(
        signal.SIGTERM, interrupted
    )

    runner = Runner(
        base,
        topology,
        inventory,
        output,
        args,
    )

    try:
        runner.preflight()
        runner.validate("inicial")

        for index, case in enumerate(cases, 1):
            print(
                f"\nCASO {index}/{len(cases)}",
                flush=True,
            )
            runner.case(case)

        bad = [
            row for row in runner.rows
            if row["result"] != "TOLERADO"
        ]

        print(
            f"\nFinal: "
            f"{len(cases) - len(bad)}/{len(cases)} "
            "casos tolerados; todos recuperados."
        )
        print(
            f"Resumen: {output / 'resumen.csv'}"
        )

        return 1 if bad else 0

    finally:
        runner.pool.shutdown(
            wait=True,
            cancel_futures=True,
        )


if __name__ == "__main__":
    try:
        raise SystemExit(main())

    except KeyboardInterrupt:
        print(
            "\nINTERRUMPIDO. Revisar el diario "
            "de recuperación si quedó alguno.",
            file=sys.stderr,
        )
        raise SystemExit(130)

    except (
        RuntimeError,
        ValueError,
        OSError,
        subprocess.TimeoutExpired,
        yaml.YAMLError,
    ) as error:
        print(
            f"\nFALLA: {error}",
            file=sys.stderr,
        )
        raise SystemExit(2)
