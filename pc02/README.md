# PC2 — Automatización de redes con Python

## Objetivo

Configurar y verificar automáticamente la topología del curso mediante
Python, Netmiko y un inventario YAML. La automatización aplica configuraciones
FRR por SSH, ejecuta write memory y guarda registros por dispositivo.

## Arquitectura

La topología contiene 30 nodos y 44 enlaces:

- AS100: 11 routers de proveedor con OSPF como IGP IPv4.
- AS200: 11 routers de proveedor con IS-IS nivel 2 como IGP.
- Cada AS contiene cinco routers de núcleo, dos RR, dos PE y dos bordes.
- Ocho routers de sitio: dos sitios por cliente dentro de cada AS.
- iBGP con Route Reflectors distribuye las rutas.
- MPLS LDP proporciona el transporte de las L3VPN.
- eBGP IPv4 conecta AS100-BORDE1 con AS200-BORDE1.

Los otros enlaces físicos entre bordes no tienen sesiones eBGP configuradas.
Por tanto, esta implementación no afirma redundancia eBGP completa.

## Clientes

| Cliente | Sitios en cada AS | Interfaz PE | VRF | Tabla Linux |
|---|---|---|---|---:|
| A | site1 y site2 | eth3 | A | 10 |
| B | site-1 y site-2 | eth4 | B | 20 |

| Cliente | Tránsitos de sitios 1 y 2 | Loopbacks de sitios 1 y 2 |
|---|---|---|
| A | 10.0.1.0/30 y 10.0.2.0/30 | 192.168.1.1 y 192.168.2.1 |
| B | 10.0.11.0/30 y 10.0.12.0/30 | 192.168.11.1 y 192.168.12.1 |

En cada tránsito, el PE utiliza .1 y el sitio .2.
Las LAN se simulan mediante loopbacks configuradas con máscara /24;
OSPF anuncia sus direcciones como rutas /32.

Cada cliente utiliza un RT común dentro de su AS: ASN:10 para A y ASN:20
para B. Los RD son distintos por PE y cliente.

Las L3VPN conectan sitios del mismo cliente dentro de cada AS.
No se implementan L3VPN inter-AS ni acceso de clientes a Internet.

La conectividad IPv4 unicast entre proveedores se prueba mediante
45.10.0.1/32 en AS100-PE2 y 50.20.0.1/32 en AS200-PE2.

## Requisitos

- Linux con Docker y Containerlab.
- Python 3 con soporte para entornos virtuales.
- Acceso a Docker y sudo en el anfitrión para desplegar.
- Kernel con MPLS y VRF.
- Imagen del curso cargada como frr:10.7.1-ssh.

La imagen del profesor debe cargarse desde su archivo TAR; no se obtiene
con docker pull frr:10.7.1-ssh.

~~~bash
docker load -i /ruta/al/archivo/frr_10.7.1-ssh.tar
docker image inspect frr:10.7.1-ssh
~~~

## Dependencias y acceso

Ejecutar las instrucciones desde la raíz del repositorio, en el anfitrión
Linux donde corre Containerlab.

~~~bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
~~~

inventory.yml contiene nombres de gestión, roles, ASN y parámetros de clientes.
Los nombres clab-sp-core-rr-lab-* se resuelven desde el anfitrión del laboratorio.

Se utiliza el usuario admin proporcionado por el curso. El programa solicita
la contraseña o la lee de PC2_PASSWORD. No se guarda en el código ni en Git.

## Preparación y despliegue

~~~bash
sudo modprobe mpls_router
sudo modprobe mpls_iptunnel
python pc02/prepare_runtime.py
containerlab validate -t pc02/escenario02.runtime.yml
sudo containerlab deploy -t pc02/escenario02.runtime.yml --max-workers 4
~~~

El preparador copia las bases a runtime/configs y genera una topología
de ejecución con los mismos nodos y enlaces. Habilita guardado integrado
y prepara los permisos necesarios para write memory.

Containerlab crea las VRF Linux y asocia las interfaces. Python configura
por SSH los protocolos y los anuncios de las VRF en FRR.

Si runtime ya existe, el preparador se detiene para no sobrescribir el estado.
Para reutilizarlo, desplegar directamente escenario02.runtime.yml.
Para una prueba limpia, destruir el laboratorio y respaldar o mover runtime
antes de preparar nuevamente.

## Configuración automática

~~~bash
python pc02/run.py --method netmiko --all
~~~

Para seleccionar nodos:

~~~bash
python pc02/run.py --method netmiko --nodes as100-pe1 as100-site-1
~~~

El programa genera archivos desde el inventario y las bases del curso,
los transfiere por SFTP sobre la conexión SSH de Netmiko, aplica con
vtysh -f, guarda con write memory y registra consultas.

La aplicación combina comandos con la configuración existente; no elimina
de forma general configuraciones ajenas al proyecto.

Los errores se registran por nodo y se continúa con los siguientes.
El programa devuelve un código distinto de cero si alguna aplicación falla.

## Validación

Después de la convergencia:

~~~bash
python pc02/validate.py
~~~

Se comprueban vecindades IGP y LDP, sesiones BGP IPv4 configuradas,
rutas VPN remotas, aislamiento de clientes y conectividad mediante ICMP.

Resultado esperado:

~~~text
Nodos validados: 30/30
~~~

El validador compara las sesiones BGP con los vecinos IPv4 activados
en los archivos generados. No exige sesiones en todos los enlaces físicos.

Estas pruebas no certifican IPv6 extremo a extremo, L3VPN inter-AS,
tolerancia a cualquier falla ni disponibilidad permanente.

## Archivos y registros

- configs/: bases del profesor; los routers no escriben en ellas.
- inventory.yml: datos de acceso y diseño.
- build_configs.py: genera configuraciones FRR.
- prepare_runtime.py: prepara las copias y la topología de ejecución.
- run.py: aplica, guarda y consulta por SSH.
- validate.py: verifica el funcionamiento por SSH.
- generated/: archivos regenerables, excluidos de Git.
- runtime/: estado modificable de los routers, excluido de Git.
- logs/aplicacion/log_<router>.txt: aplicación y guardado.
- logs/validacion/log_<router>.txt: verificaciones por dispositivo.
- logs/validacion/resumen.txt: resumen de resultados.
- check_access.py y test_connection.py: diagnósticos iniciales de acceso.

## Apagado

~~~bash
sudo containerlab destroy -t pc02/escenario02.runtime.yml --cleanup
~~~

Se conservan runtime, las bases y los registros.

## Problemas corregidos

- Módulos MPLS ausentes: carga antes del despliegue.
- Guardado parcial: configuración integrada y permisos de ejecución.
- Activación OSPF: se conserva el método de cada VRF base.
- Next-hop externo resuelto por gestión: next-hop-self en los bordes
  hacia sus vecinos iBGP IPv4.
- Lectura de IS-IS: se admiten espacios iniciales en la tabla.

## Autoría y procedencia

Wilmer Augusto Curi Orosco.
Escenario base proporcionado por el profesor en QTBlackxxx/TLN03-M-26-2.

## Evidencias finales

[Resultados y registros](docs/evidencias/README.md)

## Arranque serializado de FRR

Se observaron trabajos restart all y restart ldpd superpuestos durante el
arranque. La topología runtime ejecuta el start.sh de la imagen del profesor
bajo el init incluido en Docker. Un manejador con flock serializa los trabajos
start/stop/restart de watchfrr por contenedor, conservando el script original
y su código de salida. No se cambian temporizadores de los protocolos.

prepare_runtime.py obtiene los archivos auxiliares localmente de la imagen
frr:10.7.1-ssh y de Docker. Requiere bash y flock dentro de esa imagen.
Las bases y la imagen no se modifican. runtime/ no debe incluirse en Git.
Los registros START/END están en /run/frr/pc2-lifecycle.log de cada router.

La corrección requiere recrear el laboratorio con escenario02.runtime.yml.
Después: python pc02/run.py --method netmiko --all y python pc02/validate.py.
Se exige 30/30; no se reinicia LDP automáticamente para ocultar un fallo.
La relación causal completa con la desaparición del socket debe confirmarse
con ensayos de arranque limpio antes de declarar el problema resuelto.

## Pruebas del arranque corregido

[Resultados y evidencias](docs/evidencias/arranque-serial-20261114/README.md)
