"""Public APK download contract, independent of CLIP and the catalog."""
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from app.services.google_drive import APK_MIME, APK_NAME
from app.services.storage_errors import StorageError


def android_download_router(get_storage):
    router = APIRouter()

    @router.get("/api/app/download", tags=["Android"], response_class=StreamingResponse,
                responses={200: {"content": {APK_MIME: {"schema": {"type": "string", "format": "binary"}}}},
                           404: {"description": "Todavía no hay una APK publicada"},
                           503: {"description": "Drive no está disponible"}})
    async def download_android_app():
        storage = get_storage()
        if getattr(storage, "provider", None) != "google_drive":
            raise HTTPException(404, "La descarga de Android requiere el almacenamiento de Drive.")
        try:
            remote = await run_in_threadpool(storage.open_android_release)
        except StorageError:
            raise HTTPException(503, "No se pudo obtener la APK. Intenta descargarla de nuevo en unos minutos.") from None
        if remote is None:
            raise HTTPException(404, "La app Android todavía no está publicada. Vuelve a intentarlo más tarde.")

        def chunks():
            try:
                yield from remote.iter_content(chunk_size=64 * 1024)
            finally:
                remote.close()

        headers = {"Content-Disposition": f'attachment; filename="{APK_NAME}"',
                   "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
        size = remote.headers.get("Content-Length")
        if size and size.isdigit():
            headers["Content-Length"] = size
        return StreamingResponse(chunks(), media_type=APK_MIME, headers=headers,
                                 background=BackgroundTask(remote.close))

    return router
