import os

# Lista con los 22 routers de la topología
routers = [
    # AS 100
    "as100-rr1", "as100-rr2", "as100-p1", "as100-p2", "as100-p3", "as100-p4", "as100-p5",
    "as100-pe1", "as100-pe2", "as100-borde1", "as100-borde2",
    # AS 200
    "as200-rr1", "as200-rr2", "as200-p1", "as200-p2", "as200-p3", "as200-p4", "as200-p5",
    "as200-pe1", "as200-pe2", "as200-borde1", "as200-borde2"
]

# Contenido base del archivo daemons (Habilita todos los protocolos para el curso)
daemons_content = """zebra=yes
bgpd=yes
ospfd=yes
isisd=yes
ldpd=yes
ripd=no
ripng=no
ospf6d=yes
pimd=no
nhrpd=no
eigrpd=no
babeld=no
sharpd=no
pbrd=no
bfdd=no
fabricd=no
vrrpd=no
pathd=no
"""

print("🚀 Creando estructura de directorios persistentes...")

for router in routers:
    # Definir la ruta de la carpeta del router
    router_dir = f"./configs/{router}"
    os.makedirs(router_dir, exist_ok=True)
    
    # 1. Crear el archivo daemons
    with open(f"{router_dir}/daemons", "w") as f:
        f.write(daemons_content)
        
    # 2. Crear un archivo frr.conf base vacío con el hostname correspondiente
    frr_conf_content = f"hostname {router}\nlog syslog informational\n"
    with open(f"{router_dir}/frr.conf", "w") as f:
        f.write(frr_conf_content)

print("✅ Carpetas creadas con éxito en ./configs/")
print("👉 Ahora puedes ejecutar: sudo containerlab deploy -t topology.clab.yml")
