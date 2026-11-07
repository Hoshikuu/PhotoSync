# PhotoSync backend

API local para recibir originales de dispositivos autorizados. Destino previsto: Debian ARM en LXC, `192.168.1.202:8080`; NAS OMV NFS en `192.168.1.201`. La aplicación Android es independiente.

## Preparación del almacenamiento

Monta la exportación NFS en el **host Proxmox** y pásala al LXC como punto de montaje en `/mnt/photosync`. La exportación concreta y el identificador del contenedor dependen de la instalación. Comprueba la configuración de arranque y permisos UID/GID del LXC no privilegiado, y que el montaje dentro del contenedor muestre tipo `nfs` o `nfs4` en `/proc/self/mountinfo`. Debe permanecer montado y no caer silenciosamente al directorio local del host. Restringe el acceso NFS a los equipos necesarios.

En el recurso ya montado, crea `.photosync-storage-id` con un valor aleatorio único y pon el mismo valor en `PHOTOSYNC_STORAGE_ID`. El servicio comprueba el marcador y el tipo del montaje antes de recibir; nunca debe crearse el marcador en el directorio subyacente del host. Comprueba también que el usuario `photosync` pueda escribir. NFS puede bloquear llamadas durante una caída: prueba el comportamiento del montaje en tu instalación.

## Instalación Debian

Instala Python 3, `python3-venv` y copia este proyecto a `/opt/photosync`. Crea el usuario de sistema `photosync`, el directorio persistente `/var/lib/photosync` con permisos para él, y prepara el entorno:

```sh
cd /opt/photosync
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
sudo cp deploy/photosync.env.example /etc/photosync.env
# Edita /etc/photosync.env con el identificador real del almacenamiento.
sudo cp deploy/photosync.service /etc/systemd/system/photosync.service
sudo systemctl daemon-reload
sudo systemctl enable --now photosync
```

La IP `192.168.1.202` tiene que estar configurada en el LXC antes de arrancar. El servicio usa un solo worker; no aumentes el número, ya que el control de subidas activas es por proceso. Limita el acceso de red con el cortafuegos. Esta versión sirve HTTP sin cifrar: usa una red de confianza o un proxy TLS con certificado que el cliente pueda verificar antes de utilizar tokens en una red no confiable.

## Dispositivos

No existe emparejamiento remoto en esta primera versión. Un administrador crea un token localmente y lo introduce en el cliente mediante un canal seguro:

```sh
cd /opt/photosync
sudo -u photosync sh -c 'set -a; . /etc/photosync.env; set +a; .venv/bin/python -m photosync.admin add-device movil'
sudo -u photosync sh -c 'set -a; . /etc/photosync.env; set +a; .venv/bin/python -m photosync.admin list-devices'
sudo -u photosync sh -c 'set -a; . /etc/photosync.env; set +a; .venv/bin/python -m photosync.admin revoke-device ID'
```

El token solo se muestra al crearlo. Usa `Authorization: Bearer TOKEN` en los endpoints de copia. Los nombres y credenciales nunca se imprimen en logs de la aplicación.

## Contrato de API

La documentación interactiva está en `/docs` y el esquema en `/openapi.json`. `GET /health` devuelve 503 si el almacenamiento no está disponible. `GET /backups/status` devuelve el número y tamaño de copias del dispositivo. `POST /backups/check` recibe `{"client_ids":["id1"]}` y devuelve registros completados.

`PUT /backups/{client_id}` recibe el archivo original como cuerpo binario, con cabeceras `Authorization`, `X-Filename`, `X-File-Size` (bytes) y `X-Sha256` (hexadecimal minúsculo). El identificador debe ser estable por dispositivo, de 1 a 128 caracteres ASCII alfanuméricos, `_` o `-`. El nombre se registra como metadato y debe poder representarse en una cabecera HTTP; no controla la ruta del servidor. Conserva mismo identificador y metadatos para reintentar: una operación completada responde de nuevo sin duplicarla; metadatos distintos reciben 409. Un fallo tras mover el archivo se recupera al reintentar, verificando su hash.

La recepción es incremental, con dos subidas simultáneas y 10 GiB por archivo por defecto. Las copias terminadas se identifican por dispositivo e ID; no hay deduplicación global, restauración, limpieza automática de temporales tras caída de proceso, gestión de fechas ni subida reanudable por bloques. La API de consulta refleja la base de datos y no comprueba si cada archivo sigue en el NAS. Los archivos utilizan nombres internos sin extensión; los nombres originales se conservan en SQLite. Respalda SQLite mediante la API de backup de SQLite o con el servicio parado, además de respaldar el NAS.

## Verificación

```sh
python -m pip install pytest httpx
python -m compileall -q photosync
python -m pytest -q
```

Las pruebas usan un directorio local y desactivan la comprobación NFS exclusivamente para ellas. Antes de producción verifica NFS real, permisos, desconexión/reconexión, reinicios, integridad y consumo de RAM en la Raspberry Pi. No se ha medido el límite de 1 GB en el dispositivo real.
