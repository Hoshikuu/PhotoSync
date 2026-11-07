# PhotoSync: instalación paso a paso

PhotoSync recibe fotos y vídeos de una futura aplicación Android y guarda los originales en tu NAS. Todo funciona en la red local.

| Equipo | Función | Dirección |
| --- | --- | --- |
| NAS OpenMediaVault | Guarda los archivos y comparte una carpeta por NFS. | `192.168.1.201` |
| Host Proxmox en Raspberry Pi | Ejecuta el LXC y monta la carpeta del NAS. | La IP que ya tenga Proxmox |
| LXC Debian | Ejecuta el backend. | `192.168.1.202` |

**Lee dónde ejecutar cada comando**: unos van en Proxmox y otros en el LXC. Los comandos de Linux suponen que has entrado como `root`, mediante consola o SSH.

## Antes de empezar

Necesitas tener creado un LXC Debian ARM conectado a tu red con la IP `192.168.1.202`. Esta guía no crea el LXC ni configura su red. Comprueba que la IP está libre.

También necesitas conocer:

- El **ID del LXC** en Proxmox. Los ejemplos usan `123`; sustitúyelo por el tuyo.
- La **ruta exacta exportada por NFS** en OpenMediaVault. Los ejemplos usan `/RUTA/EXPORTADA`; sustitúyela por la ruta real. No tiene por qué ser igual al nombre del recurso SMB.
- La IP del host Proxmox y acceso de administrador a OMV, Proxmox y el LXC.
- Acceso desde el LXC a los repositorios para instalar las dependencias durante la instalación.

## 1. Preparar el recurso NFS

En **OpenMediaVault**, comprueba que la carpeta deseada esté exportada por NFS, que el host Proxmox pueda conectarse y que los permisos permitan escribir. Anota la ruta real de exportación.

En el **host Proxmox**, si tienes instalada la herramienta `showmount`, puedes consultar las exportaciones anunciadas:

```sh
showmount -e 192.168.1.201
```

Si no aparece, revisa OMV: `showmount` no es concluyente para todas las configuraciones NFS. No uses literalmente `/RUTA/EXPORTADA` en el paso siguiente.

## 2. Montar la carpeta en Proxmox

En el **host Proxmox**, cambia `/RUTA/EXPORTADA` por la ruta real de OMV:

```sh
mkdir -p /mnt/hsk/photosync
mount -t nfs 192.168.1.201:/RUTA/EXPORTADA /mnt/hsk/photosync
findmnt -T /mnt/hsk/photosync
```

Comprueba que el origen indicado pertenece al NAS y que el tipo es `nfs` o `nfs4`. Si falla o muestra otro sistema de archivos, revisa la exportación, la red y los permisos antes de seguir.

El comando anterior solo prueba el montaje: **no lo hace persistente**. Configura el montaje NFS permanente en el host, por ejemplo mediante `/etc/fstab` con las opciones adecuadas para tu instalación. Comprueba que se monta al arrancar Proxmox **antes de iniciar el LXC**. No inicies el contenedor con un directorio local vacío en lugar del NFS.

## 3. Compartir el montaje con el LXC

En el **host Proxmox**, sustituye `123` por el ID de tu contenedor:

```sh
pct config 123
pct set 123 -mp0 /mnt/hsk/photosync,mp=/mnt/hsk/photosync
```

Antes de ejecutar el segundo comando, comprueba en la salida de `pct config` que `mp0` está libre. Si no lo está, usa otro índice libre, como `-mp1`; no sobrescribas otro montaje. Reinicia el LXC si es necesario para aplicar el cambio y abre su consola.

En el **LXC Debian**:

```sh
ip -4 addr show
findmnt -T /mnt/hsk/photosync
```

La primera salida debe mostrar `192.168.1.202` y la segunda un sistema de archivos `nfs` o `nfs4`. La aplicación necesita ver NFS dentro del contenedor. Si no aparece, detente y revisa los montajes antes de continuar.

## 4. Copiar los archivos al LXC

Primero, en el **LXC Debian**, crea un directorio temporal para recibir el proyecto:

```sh
mkdir -p /opt/photosync-transfer
```

Después, desde **PowerShell en Windows**, situado en la carpeta del proyecto:

```powershell
scp -r photosync deploy requirements.txt README.md ANDROID_INTEGRATION.md root@192.168.1.202:/opt/photosync-transfer/
```

Si SSH no permite entrar como root, copia los archivos con un usuario autorizado a una carpeta donde pueda escribir y adapta la ruta del comando `cp` del paso siguiente. No copies `.venv` de Windows: el entorno Python se creará dentro de Debian ARM.

Ahora, en el **LXC Debian**, instala los archivos y dependencias:

```sh
apt update
apt install -y python3 python3-venv python3-pip curl nano
mkdir -p /opt/photosync
cp -r /opt/photosync-transfer/. /opt/photosync/
cd /opt/photosync
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Comprueba que existen `/opt/photosync/photosync/app.py` y `/opt/photosync/deploy/photosync.service`.

## 5. Crear el usuario y comprobar la escritura

En el **LXC Debian**:

```sh
adduser --system --group --home /var/lib/photosync photosync
mkdir -p /var/lib/photosync
chown photosync:photosync /var/lib/photosync
id photosync
```

La base de datos SQLite se guardará localmente en el LXC. Los originales se guardarán en el NAS. Comprueba que el usuario puede escribir en el NFS **solo después de verificar el montaje**:

```sh
runuser -u photosync -- sh -c 'touch /mnt/hsk/photosync/.photosync-write-test && rm /mnt/hsk/photosync/.photosync-write-test'
```

Si recibes `Permission denied`, detente. En un LXC no privilegiado, el UID/GID del usuario dentro del contenedor se traduce a otro en el host; OMV también puede aplicar `root_squash` y otros permisos. Revisa el mapeo y los permisos de la exportación según tu instalación. No apliques `chmod 777` ni cambies recursivamente los permisos del NAS como solución general.

## 6. Configurar el identificador del almacenamiento

El backend busca un archivo marcador para ayudar a identificar el almacenamiento. **Antes de crearlo, ejecuta `findmnt -T /mnt/hsk/photosync` y confirma que el NAS está montado.** No crees el marcador en el directorio local subyacente.

En el **LXC Debian**, copia y abre la configuración:

```sh
cp /opt/photosync/deploy/photosync.env.example /etc/photosync.env
nano /etc/photosync.env
```

Busca esta línea:

```text
PHOTOSYNC_STORAGE_ID=replace-with-a-unique-random-value
```

Sustituye el valor por una cadena aleatoria única, sin espacios ni comillas. Para generar una, abre otra consola del LXC o sal temporalmente del editor y ejecuta:

```sh
python3 -c 'import secrets; print(secrets.token_hex(32))'
```

Copia el valor en `/etc/photosync.env`. En `nano`, guarda con `Ctrl+O`, pulsa `Enter` y sal con `Ctrl+X`.

Después crea el marcador en el **NFS montado** con exactamente el mismo valor. Sustituye `PEGA_EL_MISMO_VALOR` por la cadena generada:

```sh
printf '%s\n' 'PEGA_EL_MISMO_VALOR' > /mnt/hsk/photosync/.photosync-storage-id
```

El usuario `photosync` debe poder leer el marcador y escribir en la carpeta. Mantén `PHOTOSYNC_REQUIRE_NFS=1` para el despliegue real. Si cambias la ruta de almacenamiento, tendrás que actualizar también el montaje y `ReadWritePaths` en el servicio.

## 7. Iniciar el backend

En el **LXC Debian**:

```sh
cp /opt/photosync/deploy/photosync.service /etc/systemd/system/photosync.service
systemctl daemon-reload
systemctl enable --now photosync
systemctl status photosync --no-pager
```

El servicio escucha en `192.168.1.202:8080`. Si decides usar otra IP, cambia `--host` en el servicio instalado y recarga systemd. Mantén un solo worker: el control de subidas activas de esta versión funciona por proceso. Restringe el puerto a la red local mediante el cortafuegos y no configures redirecciones en el router.

## 8. Comprobar la conexión

En el **LXC Debian**:

```sh
curl -i http://192.168.1.202:8080/health
```

Si funciona, recibirás `200 OK` y:

```json
{"status":"ok","storage_available":true}
```

Desde un ordenador conectado a la misma red puedes abrir `http://192.168.1.202:8080/docs`. Si obtienes `503`, consulta la sección de problemas. Esta comprobación por sí sola no prueba una subida real.

## 9. Crear un token para el móvil

En el **LXC Debian**:

```sh
cd /opt/photosync
runuser -u photosync -- sh -c 'set -a; . /etc/photosync.env; set +a; .venv/bin/python -m photosync.admin add-device movil'
```

Verás un `Device ID` y un `Token`. **Guarda el token de forma segura: solo se muestra una vez.** Se introducirá en la aplicación Android; todavía no hay emparejamiento por QR.

Para listar dispositivos o revocar uno, sustituye `ID_DEL_DISPOSITIVO` por el ID mostrado:

```sh
runuser -u photosync -- sh -c 'set -a; . /etc/photosync.env; set +a; .venv/bin/python -m photosync.admin list-devices'
runuser -u photosync -- sh -c 'set -a; . /etc/photosync.env; set +a; .venv/bin/python -m photosync.admin revoke-device ID_DEL_DISPOSITIVO'
```

La API usa `Authorization: Bearer TOKEN`. Esta versión utiliza HTTP sin cifrar: el token y los archivos pueden ser observados en la red. Para protegerlos en tránsito, configura HTTPS con un certificado que Android pueda verificar.

## 10. Probar una subida

Antes de usar fotos importantes, prueba con un archivo pequeño. En el **LXC Debian**, sustituye `PEGA_AQUI_EL_TOKEN` por el token creado:

```sh
printf 'prueba de PhotoSync\n' > /tmp/photosync-test.txt
SHA=$(sha256sum /tmp/photosync-test.txt | cut -d ' ' -f 1)
SIZE=$(wc -c < /tmp/photosync-test.txt | tr -d ' ')
curl -i -X PUT 'http://192.168.1.202:8080/backups/prueba_1' \
  -H 'Authorization: Bearer PEGA_AQUI_EL_TOKEN' \
  -H 'X-Filename: photosync-test.txt' \
  -H "X-File-Size: $SIZE" \
  -H "X-Sha256: $SHA" \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @/tmp/photosync-test.txt
```

Debe responder `200` con `"status":"complete"`. Repetir la misma petición no crea otra copia para ese dispositivo e ID. El token escrito en comandos puede quedar en el historial: usa un token de prueba y revócalo después si es necesario. Esta prueba deja un archivo en el NAS y su registro en SQLite.

Para desarrollar la aplicación Android, consulta [la guía de integración](./ANDROID_INTEGRATION.md).

## 11. Activar la galería en el puerto 80

La galería muestra los archivos del dispositivo correspondiente al token con el que entres. No necesita otro servidor Python: Nginx recibe las visitas en el puerto 80 y las pasa al servicio existente en el 8080. Las aplicaciones Android que usan el 8080 siguen funcionando.

Si ya tenías una instalación anterior, copia al LXC la versión actual de `photosync/` (incluida la carpeta `static/`) y `deploy/photosync-nginx.conf`, como en el paso 4. Copia el código actualizado a `/opt/photosync` sin sustituir `/etc/photosync.env`, `/var/lib/photosync` ni los archivos del NAS. Después reinicia el backend:

```sh
systemctl restart photosync
systemctl status photosync --no-pager
```

En el **LXC Debian**, instala Nginx y activa la configuración incluida:

```sh
apt update
apt install -y nginx
cp /opt/photosync/deploy/photosync-nginx.conf /etc/nginx/sites-available/photosync
ln -s /etc/nginx/sites-available/photosync /etc/nginx/sites-enabled/photosync
nginx -t
systemctl enable --now nginx
systemctl reload nginx
```

Si el enlace ya existe, no repitas `ln -s`. Si `nginx -t` o el inicio falla, comprueba `ss -ltnp | grep ':80'` y revisa la configuración existente antes de modificarla: otro servicio o sitio puede estar usando el puerto. La IP del `listen` de la configuración debe coincidir con la del LXC. Permite el puerto 80 desde la red local en el cortafuegos.

En un navegador de la misma red, abre **http://192.168.1.202/** e introduce el token del móvil. El token se mantiene solo en la memoria de la pestaña y se borra al cerrar sesión o recargar. Cada dispositivo tiene su propio token y solo se muestran sus copias completadas. La galería carga páginas de 12 archivos y muestra vistas previas de JPEG, PNG, GIF, WebP y AVIF que no superen 20 MiB; los otros archivos aparecen sin vista previa. No genera miniaturas en el servidor.

La conexión es HTTP y no cifra el token ni las fotos. Úsala en tu red de confianza; para cifrar el tráfico configura HTTPS en Nginx y un certificado que los clientes puedan verificar. No publiques el puerto en Internet. Como la galería descarga los originales para mostrarlos, comprueba el consumo de red y memoria del navegador con tu colección real.

## Problemas frecuentes

- **El servicio no arranca:** ejecuta `systemctl status photosync --no-pager` y `journalctl -u photosync -n 100 --no-pager`. Comprueba la IP, el montaje y el entorno virtual.
- **`/health` devuelve 503:** revisa `findmnt -T /mnt/hsk/photosync` dentro del LXC, el marcador, su valor en `/etc/photosync.env` y los permisos. NFS puede bloquear operaciones durante una caída; prueba la recuperación en tu instalación.
- **No se puede escribir:** revisa los permisos en OMV y el mapeo UID/GID del LXC. Root dentro del contenedor no implica acceso root al NAS.
- **La app recibe 401:** revisa el token y si el dispositivo está revocado.
- **La app recibe 409:** puede haber una subida activa o un ID reutilizado con metadatos diferentes; consulta el mensaje de respuesta.
- **Tras editar el servicio:** ejecuta `systemctl daemon-reload` y `systemctl restart photosync`. Tras editar `/etc/photosync.env`, reinicia el servicio.

## Copias de seguridad y límites

Los originales están en el NAS. Los dispositivos, nombres, hashes y rutas se guardan en `/var/lib/photosync/photosync.db`, dentro del LXC. Respalda también esa base de datos mediante la API de backup de SQLite o con el servicio detenido.

Los archivos usan nombres internos sin extensión; el nombre enviado se guarda en SQLite. La consulta de copias no comprueba cada archivo físico. Todavía no hay descarga, restauración, reanudación por bloques ni limpieza automática de temporales después de una caída. No borres los originales del teléfono basándote únicamente en la respuesta de la API.

Las pruebas automatizadas existentes usan almacenamiento local simulado. El montaje NFS real, las desconexiones, los reinicios y el objetivo de menos de 1 GB de RAM aún deben verificarse en la Raspberry Pi y el LXC reales.
