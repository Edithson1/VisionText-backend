# Descarga de la app Android

`GET /api/app/download` entrega la última `VisionText.apk` publicada en la
carpeta privada del proyecto en Google Drive. Es pública y no requiere token de
administrador. Usa las mismas variables `GOOGLE_DRIVE_*` del backend.

Contrato: respuesta 200 con `application/vnd.android.package-archive`,
`Content-Disposition: attachment; filename="VisionText.apk"` y `Cache-Control:
no-store`. Devuelve JSON con `detail` y estado 404 si no hay APK o se usa S3;
503 si falla Drive antes de iniciar la transferencia. El cuerpo se transmite
por bloques de 64 KiB y se cierra la conexión remota al terminar.

Publicación desde este repositorio, con una APK previamente compilada y firmada:

```powershell
python scripts/publish_android_apk.py --apk RUTA_A_LA_APK --version-name 1.3 --version-code 4
```

El script usa `.env.drive` o las variables del entorno (prioridad al entorno).
Admite `--env-file RUTA` y `--check`. Verifica el ZIP Android y los datos de
integridad devueltos por Drive; guarda versión, ID y SHA-256 junto a la APK.
Crea o actualiza un archivo con `visiontext_kind=android_apk`, dentro de la
carpeta raíz configurada y el namespace del proyecto. Mantiene el mismo ID al
actualizarlo y no crea permisos públicos en Drive. No permite seleccionar otros
archivos mediante parámetros de la ruta de descarga.

El flujo completo de compilación de Windows está en `Publicar-App.ps1`, en la
carpeta que contiene los tres proyectos VisionText. Conserva su firma privada
en `VisionText-android/.signing/`; hay que respaldarla para futuras actualizaciones.

Pruebas HTTP locales: `pytest tests/test_android_download.py tests/test_google_drive.py -q`.
Reutilizan `tests/drive_emulator.py` con creación, actualización multipart,
OAuth y descarga. Postman CLI no está instalado; se conserva este simulador
existente. Orbit no resolvió su host durante esta sesión; el contrato se cotejó
con la documentación oficial de Google:
[files.update](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/update)
y [descargas](https://developers.google.com/workspace/drive/api/guides/manage-downloads).
