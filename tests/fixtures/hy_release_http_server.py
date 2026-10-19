"""Z browser fixture: real isolated HTTP/Runtime/SDK, synthetic model only."""

import argparse
import asyncio
from datetime import UTC, datetime
import hmac
import json
import os
from pathlib import Path

from aiohttp import web

from longmemory.bootstrap import build_hy_memory_runtime
from longmemory.entrypoints.api.react_assets import register_react_routes
from longmemory.entrypoints.api.routes.memory_engine import register_memory_engine_routes
from longmemory.entrypoints.api.security import Sessions, security_middleware
from longmemory.methods.contracts import MemoryEvent
from longmemory.methods.hy_memory.settings import HySettings
from longmemory.methods.hy_memory.assembly import management_primitives_identity


async def run(args):
    if args.port in {8767, 8000, 8003} or not 1024 <= args.port <= 65535:
        raise ValueError("isolated port required")
    if args.state.exists():
        raise FileExistsError("new synthetic state directory required")
    args.state.mkdir(parents=True)
    runtime = build_hy_memory_runtime(
        settings=HySettings(user_id="z-browser-synthetic", model_mode="synthetic_transport", management_writes_enabled=True),
        state_directory=args.state / "engine", source_path=args.state / "sources.db",
        create=True, python=Path(os.environ["LONGMEMORY_TEST_HY_PYTHON"]),
        management_verification={"sdk_version":"2.0.3", "rpc_source_sha256":management_primitives_identity(),
            "real_sdk_rpc_verified":True, "semantic_background_writes_disabled":True})
    stop = asyncio.Event()
    sessions = Sessions()
    app = web.Application(middlewares=[security_middleware(f"127.0.0.1:{args.port}", sessions)])
    runner = web.AppRunner(app, access_log=None)
    try:
        admin = runtime.backend_assembly.management
        assert admin.method._client.state._lease is not None
        assert admin.serialized_writes
        event = MemoryEvent("z-browser-seed", "user", "合成用户喜欢无糖乌龙茶",
                            datetime(2026, 10, 19, tzinfo=UTC), "z-browser-session")
        assert runtime._method.observe(event).processing_status == "completed"

        async def session(_request):
            identity, csrf = sessions.create()
            response = web.json_response({"csrf": csrf})
            response.set_cookie("lm_console_session", identity, httponly=True)
            return response

        async def config(_request):
            return web.json_response({"configured": True, "method": runtime._method.name,
                "representation": "method_defined", "database": None,
                "management_capabilities": {"listing": True, "detail": True}})

        async def finish(request):
            if not hmac.compare_digest(request.headers.get("Authorization", ""),
                                       "Bearer " + os.environ["Z_HY_TEST_STOP_TOKEN"]):
                raise web.HTTPForbidden()
            stop.set()
            return web.json_response({"stopping": True})

        app.router.add_get("/api/session", session)
        app.router.add_get("/api/memory-config", config)
        app.router.add_post("/__z_test_stop__", finish)
        register_memory_engine_routes(app, runtime, allow_correction=True, allow_delete=True)
        register_react_routes(app, args.build)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", args.port).start()
        print(json.dumps({"ready": True, "port": args.port, "source": str(Path(__file__).resolve()),
                          "settings_identity": runtime._method.engine.settings.identity()}), flush=True)
        await stop.wait()
    finally:
        await runner.cleanup()
        diagnostics = runtime._method.engine.sdk_call("diagnostics")
        assert diagnostics["external_http_attempts"] == 0
        runtime.close()
        print(json.dumps({"closed": True, "external_http_attempts": diagnostics["external_http_attempts"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
