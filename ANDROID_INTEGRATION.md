# Integración Android con PhotoSync

Esta guía describe el backend existente. La aplicación Android se desarrolla por separado y se comunica con él mediante HTTP en la red local; no necesita acceder a NFS ni a SMB. Las dependencias de `requirements.txt` son del servidor Python, no de Android.

## Dirección y seguridad

La dirección prevista es `http://192.168.1.202:8080`. Permite cambiarla en la configuración de la app. El backend usa HTTP sin cifrar: el token y los archivos son visibles para quien pueda observar el tráfico. Para una instalación más segura, añade HTTPS al despliegue y configura en Android la confianza en el certificado correspondiente.

Declara el permiso `INTERNET`. Para conectar mediante HTTP, configura explícitamente la política de seguridad de red de Android; las aplicaciones dirigidas a versiones modernas suelen bloquear el tráfico sin cifrar por defecto. Consulta la [documentación de configuración de seguridad de Android](https://developer.android.com/privacy-and-security/security-config).

## Autenticación

Un administrador crea un token por dispositivo desde el LXC mediante `photosync.admin add-device`; el procedimiento está en el [README](./README.md). El token solo se muestra al crearlo. El usuario debe introducirlo en la aplicación mediante un canal seguro: todavía no hay emparejamiento remoto ni por QR.

Guarda el token de manera segura, protegiendo la clave de cifrado mediante Android Keystore. No lo incluyas en logs, informes ni pantallas de diagnóstico. Las peticiones protegidas requieren:

```http
Authorization: Bearer TOKEN_DEL_DISPOSITIVO
```

Un token revocado o inválido produce `401`. Los archivos y sus identificadores pertenecen al dispositivo asociado al token; crear otro dispositivo no recupera automáticamente la asociación anterior.

## Acceso a fotos y vídeos

La aplicación puede permitir seleccionar archivos concretos o solicitar el acceso necesario para buscar los archivos autorizados automáticamente. Gestiona los permisos apropiados para cada versión de Android y la posibilidad de que el usuario solo conceda acceso parcial. No interpretes una biblioteca parcialmente visible como si estuviera vacía. Consulta [acceso parcial a fotos y vídeos](https://developer.android.com/about/versions/14/changes/partial-photo-video-access).

Lee los URI mediante `ContentResolver`, sin asumir que son rutas de archivo normales. Comprueba que la app siga teniendo acceso cuando el trabajo se ejecute en segundo plano; según el mecanismo de selección, el permiso puede ser temporal o requerir que se conserve explícitamente cuando esté permitido.

## Identidad y metadatos

Genera y guarda un `client_id` estable para cada archivo. Debe tener entre 1 y 128 caracteres ASCII: letras, dígitos, `_` o `-`. Un UUID guardado por la app es válido. Utiliza el mismo ID, nombre, tamaño y hash en los reintentos. Si cambia el contenido, trátalo como una nueva versión con otro ID; reutilizar el ID con metadatos diferentes produce `409`.

Antes de subir, calcula el tamaño exacto en bytes y SHA-256 como 64 caracteres hexadecimales en minúscula. Lee el contenido en bloques para evitar cargarlo entero en memoria. Como el hash se envía antes del cuerpo, normalmente necesitarás una lectura para calcularlo y otra para subir. Si el archivo cambia entre ambas, el servidor rechazará la copia.

El nombre se envía en la cabecera `X-Filename`: el contrato actual no define cómo transportar nombres Unicode arbitrarios. Utiliza un nombre ASCII seguro y estable para la primera integración. Si hay que preservar el nombre original completo, amplía antes el contrato del servidor; este no decodifica automáticamente nombres codificados en URL.

## Subir un archivo

Envía un `PUT` a `/backups/{client_id}`. El cuerpo es el archivo binario original, no JSON ni `multipart/form-data`:

```http
PUT /backups/a8e6b377-1029-4cc8-bde9-5ef3439c9832 HTTP/1.1
Host: 192.168.1.202:8080
Authorization: Bearer TOKEN_DEL_DISPOSITIVO
Content-Type: application/octet-stream
X-Filename: IMG_1234.jpg
X-File-Size: 1234567
X-Sha256: SHA256_REAL_DE_64_CARACTERES_HEXADECIMALES

[bytes originales]
```

Respuesta correcta:

```json
{
  "client_id": "a8e6b377-1029-4cc8-bde9-5ef3439c9832",
  "status": "complete",
  "sha256": "hash_real_en_hexadecimal"
}
```

Marca la copia como completada solo tras una respuesta satisfactoria con `status: complete` y el hash esperado. Si se pierde la respuesta, repite con el mismo ID y metadatos: si ya terminó, el servidor devuelve el resultado existente. Si se interrumpe antes, la subida puede tener que empezar desde el principio; no existe reanudación por bloques.

Los valores iniciales del servidor son dos subidas simultáneas y un máximo de 10 GiB por archivo; son configurables. Empieza con una sola subida desde Android y prueba antes de aumentar la concurrencia.

## Consultar copias

`POST /backups/check` recibe como máximo 500 identificadores por petición:

```http
POST /backups/check HTTP/1.1
Authorization: Bearer TOKEN_DEL_DISPOSITIVO
Content-Type: application/json

{"client_ids": ["id_foto_1", "id_foto_2"]}
```

```json
{
  "backups": [
    {"client_id": "id_foto_1", "size": 1234567, "sha256": "hash_real_en_hexadecimal"}
  ]
}
```

Solo devuelve registros completados. Compara también tamaño y hash con el archivo local antes de considerarlo respaldado.

`GET /backups/status`, autenticado, devuelve el número de registros y el total de bytes:

```json
{"count": 42, "bytes": 987654321}
```

Ambos endpoints consultan SQLite y no comprueban en ese momento que cada archivo siga existiendo físicamente en el NAS.

`GET /health` no necesita token y devuelve `200` cuando el almacenamiento parece disponible y `503` cuando no lo está. Un timeout o fallo de conexión también puede indicar que el LXC o la red no están disponibles.

Con el servidor en marcha, la documentación interactiva está en `http://192.168.1.202:8080/docs` y el esquema OpenAPI en `http://192.168.1.202:8080/openapi.json`.

## Cola y ejecución en segundo plano

Mantén una cola persistente local, por ejemplo en Room, con URI, ID, nombre, tamaño, hash, estado y número de intentos. WorkManager puede gestionar trabajos en segundo plano; Android puede aplazarlos, por lo que la interfaz debe mostrar el estado. Permite restricciones como solo Wi-Fi o solo mientras carga.

| Resultado | Tratamiento recomendado |
| --- | --- |
| `200` y `complete` | Comprueba el hash y marca la copia como completada. |
| `401` | Detén la cola y solicita revisar o sustituir el token. |
| `409` | Puede ser una subida ya activa o un ID con metadatos diferentes. Revisa el detalle antes de actuar. |
| `413` | El cuerpo recibido supera el tamaño declarado; revisa metadatos y lectura. |
| `422` | Hay datos inválidos, un tamaño superior al límite o una discrepancia de tamaño/hash; revisa el detalle. |
| `503` | Conserva la copia en cola y reintenta con espera progresiva. |
| Sin conexión o timeout | Conserva la copia en cola y reintenta con los mismos datos: el servidor puede haber terminado aunque se perdiera la respuesta. |
| `500` | Muestra que hay que revisar el servidor; no registres el token. |

## Limitaciones actuales

El backend todavía no ofrece descarga, restauración, borrado remoto, galería, deduplicación global ni emparejamiento remoto. Tampoco registra como campos separados la fecha de captura, álbum o tipo MIME. El nombre enviado se guarda en SQLite y el archivo se almacena con un nombre interno sin extensión.

No ofrezcas borrar originales del teléfono basándote solo en la información de SQLite: faltan una verificación física de las copias y un flujo de restauración probado. Las pruebas existentes utilizan almacenamiento local simulado; todavía falta comprobar la integración real con LXC y NAS, los cortes de red y el consumo de memoria en la Raspberry Pi.
