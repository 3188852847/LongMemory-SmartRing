"""动态壁纸素材库 API；不提供原视频下载，也不在此路由发布真机。"""

from __future__ import annotations

import asyncio

from aiohttp import web

from longmemory.infrastructure.media.round_wallpaper import (
    MediaProbeError,
    MediaToolUnavailable,
    RoundWallpaperTranscodeSpec,
)
from longmemory.infrastructure.media.round_wallpaper_library import MAX_SOURCE_BYTES


def _spec(request: web.Request) -> RoundWallpaperTranscodeSpec:
    if set(request.query) != {"start_seconds", "duration_seconds", "frame_rate", "colors"}:
        raise MediaProbeError("invalid_wallpaper_options")
    try:
        spec = RoundWallpaperTranscodeSpec(
            start_seconds=float(request.query["start_seconds"]),
            duration_seconds=float(request.query["duration_seconds"]),
            frame_rate=int(request.query["frame_rate"]),
            colors=int(request.query["colors"]),
        )
    except (TypeError, ValueError) as error:
        raise MediaProbeError("invalid_wallpaper_options") from error
    spec.validate()
    return spec


def register_round_wallpaper_routes(app, library):
    async def listing(_request):
        try:
            return web.json_response(library.describe())
        except (OSError, ValueError, UnicodeError):
            return web.json_response({"error": "round_wallpaper_library_unavailable"}, status=503)

    async def upload(request):
        directory = None
        try:
            if not request.content_type.startswith("multipart/form-data"):
                raise MediaProbeError("invalid_wallpaper_upload")
            content_length = request.content_length
            if content_length is not None and content_length > MAX_SOURCE_BYTES + 1024 * 1024:
                return web.json_response({"error": "wallpaper_upload_too_large"}, status=413)
            spec = _spec(request)
            cloned = request.clone(client_max_size=MAX_SOURCE_BYTES + 1024 * 1024)
            reader = await cloned.multipart()
            part = await reader.next()
            if part is None or part.name != "file" or not part.filename:
                raise MediaProbeError("invalid_wallpaper_upload")
            directory, source = library.create_staging()
            total = 0
            with source.open("xb") as output:
                while True:
                    chunk = await part.read_chunk(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_SOURCE_BYTES:
                        return web.json_response({"error": "wallpaper_upload_too_large"}, status=413)
                    output.write(chunk)
            if total == 0 or await reader.next() is not None:
                raise MediaProbeError("invalid_wallpaper_upload")
            result = await asyncio.to_thread(
                library.import_staging,
                directory,
                original_filename=part.filename,
                spec=spec,
            )
            directory = None
            return web.json_response({"item": result}, status=201)
        except MediaToolUnavailable as error:
            return web.json_response({"error": str(error)}, status=503)
        except MediaProbeError as error:
            return web.json_response({"error": str(error)}, status=400)
        except (OSError, ValueError, UnicodeError):
            return web.json_response({"error": "round_wallpaper_import_failed"}, status=503)
        finally:
            if directory is not None:
                library.discard_staging(directory)

    async def preview(request):
        try:
            path = await asyncio.to_thread(library.preview_path, request.match_info["item_id"])
            response = web.FileResponse(path, headers={"Content-Disposition": "inline; filename=preview.gif"})
            response.content_type = "image/gif"
            return response
        except (OSError, ValueError, UnicodeError, MediaProbeError):
            return web.json_response({"error": "round_wallpaper_not_found"}, status=404)

    app.router.add_get("/api/round-wallpapers", listing, allow_head=False)
    app.router.add_post("/api/round-wallpapers", upload)
    app.router.add_get("/api/round-wallpapers/{item_id}/preview", preview, allow_head=False)
