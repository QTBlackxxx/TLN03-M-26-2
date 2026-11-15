# Evidencias finales de PC2

Prueba realizada desde copias nuevas de las configuraciones base,
en la VM Ubuntu del autor con la imagen del curso y las dependencias instaladas.

## Resultados

- Aplicación y guardado por SSH: 30/30 nodos.
- Validación operativa: 30/30 nodos.
- Vecindades IGP y LDP comprobadas.
- Sesiones BGP IPv4 configuradas comprobadas.
- Rutas VPN remotas presentes en las VRF A y B.
- Conectividad entre sitios de cada cliente dentro de cada AS.
- Aislamiento de rutas y pruebas ICMP entre clientes distintos.
- Conectividad IPv4 entre las direcciones de prueba de ambos proveedores.
- Configuraciones base sin modificaciones tras la ejecución.

## Archivos

- aplicacion/: aplicación, write memory y consultas por nodo.
- validacion/: verificaciones operativas por nodo.
- reproducibilidad.txt: registro del despliegue y ejecución desde bases limpias.

## Alcance

La prueba no equivale a una instalación en otra máquina sin dependencias.
No certifica IPv6 extremo a extremo, L3VPN inter-AS ni tolerancia a cualquier falla.
