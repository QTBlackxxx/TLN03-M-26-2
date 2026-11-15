# TLN03 - Automatización y Programabilidad de Redes

## Práctica calificada 2: automatización con Python y Netmiko

**Autor:** Wilmer Augusto Curi Orosco.
**Escenario base:** [QTBlackxxx/TLN03-M-26-2](https://github.com/QTBlackxxx/TLN03-M-26-2/tree/main/pc02).

La implementación de PC2 está en [pc02/](pc02/). Configura por SSH los
30 dispositivos de la topología sp-core-rr-lab, guarda sus configuraciones
y verifica protocolos y conectividad. Se utilizan el inventario YAML y la
imagen del curso frr:10.7.1-ssh.

### Inicio rápido

Requisitos previos: Linux con Docker, Containerlab, Python 3 con venv/pip,
acceso a Docker con el usuario actual, sudo y la imagen del curso cargada.

Clonar el repositorio completo:

~~~bash
git clone --branch main https://github.com/WilmerCO21/TLN03-M-26-2.git PC2-WilmerCO21
cd PC2-WilmerCO21
~~~

Ejecutar **cada etapa por separado**, en este orden:

~~~bash
bash pc02/desplegar.sh
~~~

~~~bash
bash pc02/configurar.sh
~~~

~~~bash
bash pc02/validar.sh
~~~

SSH de la imagen del laboratorio: usuario **admin**, contraseña **admin**.
sudo utiliza la contraseña del usuario del anfitrión Linux.

El despliegue prepara las dependencias y crea los 30 FRR sin configuración
de enrutamiento de la práctica. Conserva SSH, los procesos FRR y la gestión.
No precarga IGP, BGP, LDP, direcciones de datos ni VRF. Si existe un laboratorio
de esa carpeta, lo retira y respalda runtime antes de crear uno nuevo vacío.
Interrumpe el tráfico. Si pertenece a otra copia, se detiene antes de retirarlo.

Antes de configurar, exige `Routers vacíos comprobados: 30/30` y guarda
la evidencia en `pc02/logs/antes-python/`. Después, configurar.sh ejecuta Python,
prepara las VRF Linux de los PE mediante Docker y aplica FRR por SSH/Netmiko.
Los archivos del profesor se utilizan como plantillas al configurar,
no como configuración inicial de los contenedores.

### Verificación del nuevo arranque vacío

Esta corrección requiere repetir en la VM el ciclo: 30/30 vacíos antes de
Python, 30/30 aplicaciones y 30/30 validaciones después. Las pruebas históricas
siguientes corresponden al despliegue anterior desde las bases del profesor;
no prueban por sí solas este nuevo arranque vacío.

### Resultados históricos comprobados

| Ensayo | Resultado |
|---|---|
| Aplicación y guardado por SSH | 30/30 |
| Validación operativa | 30/30 |
| Fallas individuales de la suite demo | 8/8 toleradas y recuperadas |
| Despliegue desde un clon nuevo y un entorno Python nuevo | 30/30 |
| Tres comandos independientes | Despliegue, configuración y validación comprobados |

Los ensayos se realizaron en la VM Ubuntu del autor con las dependencias
y la imagen del curso disponibles. Las fallas de router de la suite demo
son aislamientos de interfaces de datos, y hubo pérdidas transitorias en
algunas convergencias. Las L3VPN conectan sitios del mismo AS.

### Guía de revisión

- [README completo de PC2](pc02/README.md): arquitectura, requisitos, ejecución y alcance.
- [Código principal de configuración](pc02/run.py).
- [Inventario](pc02/inventory.yml) y [dependencias](requirements.txt).
- [Corrección del arranque FRR](pc02/startup_support.py).
- [Evidencias de arranque, validación y ocho fallas](pc02/docs/evidencias/arranque-serial-20261114/README.md).
- [Evidencia de reproducción desde GitHub](pc02/docs/evidencias/reproducibilidad-clon-20261114/README.md).

### Presentación

El enunciado también exige una PPT de máximo 12 diapositivas y una exposición
de hasta 10 minutos. Este repositorio todavía no incluye el archivo ni un
enlace a esa presentación.

### Otras prácticas

Las carpetas CL/, LAB-01/ y pc01/ conservan otros trabajos del curso.
La revisión de esta entrega corresponde a pc02/.
