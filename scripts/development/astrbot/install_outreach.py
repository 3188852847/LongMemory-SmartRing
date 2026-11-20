"""Install the SmartRing integration in the selected private companion 7.2.7 package."""
import argparse
from pathlib import Path
from tempfile import NamedTemporaryFile


PLAN = "        request = plan_request_for(base, job, records)\n        fits, detail ="
WRITE = "            fits, detail = self._contact_request_fits(run, request) if ("
JUDGE = "        completion = await self.gateway.generate(run, judge_request(entry))"
SEND = """            if self.private_account_router is not None:
                request = DeliveryRequest.restore(self._row(envelope.part_id)["request_json"])
                receipt = await self.private_account_router.send(envelope, request, self.sender)
            else:
                receipt = await self.sender.send(envelope)"""

EDITS = {
    "proactive/service.py": [
        ("from .configuration import GROUP", "from companion_v2.smartring_outreach import with_shared_context\n\nfrom .configuration import GROUP"),
        (PLAN, """        request = plan_request_for(base, job, records)
        if not job.administrator_test:
            request = await with_shared_context(request, job.context, job.intent.thought.summary)
        fits, detail ="""),
        (WRITE, """            if not job.administrator_test and (job.plan is None or job.plan["decision"] == "send"):
                request = await with_shared_context(request, job.context, job.intent.thought.summary)
""" + WRITE),
        (JUDGE, """        request = judge_request(entry)
        if not data.get("administrator_test"):
            request = await with_shared_context(request, context, row["body"])
        completion = await self.gateway.generate(run, request)"""),
        ('            if provenance is not None:\n                document["news_provenance"]',
         '''            if self.schedule is not None:
                document["smartring_idle_seconds"] = self.schedule.rhythm.idle_seconds(preferences)
            if job.intent.purpose == "greeting":
                document["smartring_idle_seconds"] = max(document.get("smartring_idle_seconds", 0),
                                                        preferences.values["greeting_idle_minutes"] * 60)
            if provenance is not None:
                document["news_provenance"]'''),
    ],
    "delivery/service.py": [
        ("from .models import DeliveryEnvelope, DeliveryReceipt",
         "from companion_v2.smartring_outreach import send_shared\n\nfrom .models import DeliveryEnvelope, DeliveryReceipt"),
        (SEND, '''            request = DeliveryRequest.restore(self._row(envelope.part_id)["request_json"])
            receipt = await send_shared(self, request, envelope)
            if receipt is None:
                if self.private_account_router is not None:
                    receipt = await self.private_account_router.send(envelope, request, self.sender)
                else:
                    receipt = await self.sender.send(envelope)'''),
    ],
    "../astrbot_host/account_recovery.py": [
        ("app.contact_schedule.bind_context(context)", "app.contact_schedule.bind_context(context, instruction)"),
    ],
    "../astrbot_host/core_reply_maintenance.py": [
        ("app.contact_schedule.bind_context(context)", "app.contact_schedule.bind_context(context, instruction)"),
    ],
    "proactive/scheduling.py": [
        ("    def bind_context(self, context):", "    def bind_context(self, context, instruction=None):"),
        ("        self._maintenance_contexts[context.key] = context",
         """        self._maintenance_contexts[context.key] = context
        from companion_v2.smartring_outreach import bind_shared_target
        bind_shared_target(self, context, instruction)"""),
        ('        return native if native is not None and (legacy is None or native["observed_at"] >= legacy["created_at"]) else legacy',
         '''        latest = native if native is not None and (legacy is None or native["observed_at"] >= legacy["created_at"]) else legacy
        shared = getattr(self.contacts.history, "smartring_activity", None)
        if shared and shared["origin_key"] == context.key and (latest is None or shared["user_at"] > latest["created_at"]):
            return shared
        return latest'''),
        ("        fallback_input = False", """        from companion_v2.smartring_outreach import shared_origin
        shared = shared_origin(self, context, batch_id, at, max(
            row["created_at"] if row else "", native["observed_at"] if native else ""))
        if shared is not None:
            return shared
        fallback_input = False"""),
        ("        return now, rows, available, len(legacy_rows), len(native_rows)",
         """        shared = getattr(self.contacts.history, "smartring_activity", None)
        if shared is not None:
            rows = (shared, *rows)
        return now, rows, available, len(legacy_rows), len(native_rows)"""),
        ("    def _row_cursor(self, row):", """    def _row_cursor(self, row):
        if isinstance(row, dict) and row.get("execution_path") == "shared":
            return"""),
        ("        self._advancing = True\n        try:\n            prepared = self._begin_tick()",
         """        self._advancing = True
        try:
            from companion_v2.smartring_outreach import refresh_activity
            await refresh_activity(self)
            prepared = self._begin_tick()"""),
    ],
    "delivery/history.py": [
        ('        counts = self.runtime.read_one("""SELECT\n            COUNT(DISTINCT CASE WHEN state',
         '''        shared = getattr(self, "smartring_activity", None)
        if (shared and shared["origin_key"] == context.key and shared["user_at"] <= stamp(at)
                and (last_at is None or shared["user_at"] > last_at)):
            last_at = shared["user_at"]
            input_reference = {"event_key": shared["batch_id"], "event_hash": digest(shared["batch_id"])}
        counts = self.runtime.read_one("""SELECT
            COUNT(DISTINCT CASE WHEN state'''),
    ],
}


def install(plugin):
    version = (plugin / "metadata.yaml").read_text("utf-8").splitlines()
    if "version: 7.2.7" not in version or "name: astrbot_plugin_private_companion" not in version:
        raise ValueError("需要已核对的 astrbot_plugin_private_companion 7.2.7")
    package = plugin / "companion_v2"
    files = {package / "smartring_outreach.py": Path(__file__).with_name("companion_outreach.py").read_bytes()}
    for relative, edits in EDITS.items():
        path = package / relative
        before = path.read_bytes()
        source = before.decode().replace("\r\n", "\n")
        for old, new in edits:
            if source.count(new) == 1:
                continue
            if source.count(old) != 1:
                raise ValueError(f"{relative} 的上游实现已变化，未应用接入修改")
            source = source.replace(old, new)
        compile(source, str(path), "exec")
        files[path] = source.replace("\n", "\r\n" if b"\r\n" in before else "\n").encode()
    for path, content in files.items():
        if path.is_file() and path.read_bytes() == content:
            continue
        with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            stream.write(content)
        Path(stream.name).replace(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plugin", type=Path)
    install(parser.parse_args().plugin)
