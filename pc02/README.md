# PC2 — Automatización de redes con Python

## Objetivo

Configurar y verificar automáticamente la topología del curso mediante
Python, Netmiko y un inventario YAML. La automatización aplica configuraciones
FRR por SSH, ejecuta write memory y guarda registros por dispositivo.

## Inicio rápido

Los tres comandos siguientes son la forma recomendada de ejecutar esta entrega.
Se ejecutan en el anfitrión Linux donde corre Containerlab, desde la raíz
del repositorio. Requieren Docker, Containerlab, Python 3 con venv/pip,
acceso a Docker, sudo y la imagen del curso frr:10.7.1-ssh cargada.

### Obtener el código

~~~bash
git clone --branch main https://github.com/WilmerCO21/TLN03-M-26-2.git PC2-WilmerCO21
cd PC2-WilmerCO21
~~~

### 1. Desplegar

~~~bash
bash pc02/desplegar.sh
~~~

Prepara el entorno virtual, instala requirements.txt y carga los módulos MPLS.
Retira el laboratorio de esta carpeta, respalda el runtime anterior y crea
uno nuevo sin configuración de enrutamiento de la práctica. Conserva gestión,
SSH, hostname y procesos FRR. No precarga IP de datos, IGP, BGP, LDP ni VRF.
Si pertenece a otra copia del repositorio, se detiene antes de retirarlo.
Al terminar exige `Routers vacíos comprobados: 30/30` y guarda evidencia
por nodo en logs/antes-python/. El despliegue interrumpe el tráfico previo.

### 2. Configurar y guardar

~~~bash
bash pc02/configurar.sh
~~~

Ejecuta Python/Netmiko para los 30 nodos. Python crea las VRF Linux de los PE
mediante Docker local y aplica por SSH sus configuraciones FRR completas.
Utiliza las bases del profesor como plantillas, genera los bloques de clientes,
guarda con write memory y espera 60 segundos de convergencia. Resultado esperado: Aplicaciones confirmadas: 30/30.

### 3. Validar

~~~bash
bash pc02/validar.sh
~~~

Ejecuta únicamente la verificación operativa. Resultado esperado: Nodos validados: 30/30.

El acceso SSH de la imagen del laboratorio es admin/admin. sudo solicita
la contraseña del usuario del anfitrión. Los programas solicitan la clave SSH
o la leen de PC2_PASSWORD; no la escriben en los registros.

### Prueba requerida del nuevo modo vacío

Ejecutar desplegar.sh, comprobar 30/30 vacíos, ejecutar configurar.sh y exigir
30/30 aplicaciones, y finalmente validar.sh con 30/30. Hasta completar esa
prueba, los registros históricos siguientes no certifican este modo nuevo.

### Resultados y evidencias históricas

Se comprobaron aplicación y validación 30/30, ocho fallas individuales
toleradas con recuperación completa y reproducción desde un clon nuevo
con un entorno Python nuevo, en la misma VM Ubuntu del autor.

- [Arranque corregido, registros por nodo y ocho fallas](docs/evidencias/arranque-serial-20261114/README.md).
- [Despliegue desde un clon nuevo de GitHub](docs/evidencias/reproducibilidad-clon-20261114/README.md).

El código de los tres comandos está en [desplegar.sh](desplegar.sh),
[configurar.sh](configurar.sh) y [validar.sh](validar.sh).
Las secciones de ejecución manual permiten revisar las etapas internas.

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

## Dependencias y acceso: ejecución manual

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
la contraseña o la lee de PC2_PASSWORD; no la escribe en sus registros.

## Preparación y despliegue manual

~~~bash
sudo modprobe mpls_router
sudo modprobe mpls_iptunnel
python pc02/prepare_runtime.py
containerlab validate -t pc02/escenario02.runtime.yml
sudo containerlab deploy -t pc02/escenario02.runtime.yml --max-workers 4
~~~

El preparador copia solo daemons y crea frr.conf mínimo y vtysh.conf en
runtime/configs. No copia ningún .conf del profesor. Genera una topología
con los mismos nodos y enlaces, conserva el arranque serializado y prepara
los permisos para write memory.

Las VRF Linux y sus asociaciones de puertos se crean en run.py durante la
fase de configuración, mediante Docker como root en los PE. El usuario
admin sigue aplicando por SSH/Netmiko los protocolos y anuncios FRR.

Si runtime ya existe, el preparador se detiene para no sobrescribir el estado.
Desplegar directamente un runtime ya configurado conserva su configuración.
Para la demostración desde routers vacíos, utilizar desplegar.sh, que respalda
el estado anterior y prepara uno nuevo sin configuración de la práctica.

## Configuración automática: comando Python

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

## Validación: comando Python

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

- configs/: plantillas del profesor; no se montan en los routers.
- inventory.yml: datos de acceso y diseño.
- build_configs.py: genera configuraciones FRR.
- prepare_runtime.py: prepara FRR mínimo y la topología de ejecución.
- check_empty.py: registra y comprueba los 30 routers antes de configurar.
- linux_vrf.py: crea VRF Linux durante la fase de configuración.
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

- Arranque preconfigurado: se reemplaza la copia de bases por FRR mínimo.
  Cada despliegue respalda runtime y exige comprobar 30/30 vacíos antes de Python.

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
El cambio se verificó mediante arranques limpios con validación 30/30 y
reproducción desde GitHub. Los registros originales muestran reinicios
solapados; no se identificó el proceso exacto que retiró el socket.

## Pruebas del arranque corregido

[Resultados y evidencias](docs/evidencias/arranque-serial-20261114/README.md)

## Reproducción desde GitHub

[Prueba desde un clon nuevo: 30/30](docs/evidencias/reproducibilidad-clon-20261114/README.md)

## Pruebas de fallas adicionales

Con la red configurada y validada, ejecutar desde la raíz del repositorio:

~~~bash
.venv/bin/python pc02/test_failover.py --suite demo --execute
~~~

La suite demo ejecuta ocho casos, uno a la vez: caída de eth2 de PE1,
aislamiento de los cuatro puertos de datos de P5, caída de eth1 de PE2 y
caída de eth2 de P2, en AS100 y AS200. Restaura cada caso y exige recuperación
completa antes de continuar. Los casos de router aíslan interfaces; no apagan
el contenedor. Se observaron pérdidas transitorias durante algunas convergencias.

Los ocho casos ensayados fueron tolerados. Esto no certifica todas las fallas
posibles ni redundancia eBGP completa. Los resultados están en
[resumen.csv](docs/evidencias/arranque-serial-20261114/resumen.csv).
