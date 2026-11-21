from contextlib import ExitStack
from tempfile import SpooledTemporaryFile, TemporaryFile
import unittest
from unittest.mock import patch

from fastapi import FastAPI, File, Form, UploadFile
import httpx

from app.workspace_http_common import INTAKE_BYTES, MAX_MULTIPART_BYTES, MultipartBodyLimit


def packet(note=True):
    parts = []
    for role in ("bill", "letter", "records", "summary"):
        parts.append(f'--demo\r\nContent-Disposition: form-data; name="files"; filename="{role}.pdf"\r\n'
                     f'Content-Type: application/pdf\r\n\r\nExample {role}\r\n')
    if note:
        parts.append('--demo\r\nContent-Disposition: form-data; name="note"\r\n\r\nExample case\r\n')
    parts.append("--demo--\r\n")
    return "".join(parts).encode()


class UploadLimitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app = FastAPI()
        self.body = packet()

        @app.post("/api/test")
        async def inspect(files: list[UploadFile] = File(), note: str = Form()):
            contents = [(file.filename, (await file.read()).decode()) for file in files]
            return {"contents": contents, "note": note}

        self.app = app
        self.client = self.limited_client(len(self.body))
        self.addAsyncCleanup(self.client.aclose)
        self.headers = {"Content-Type": "multipart/form-data; boundary=demo"}

    def limited_client(self, maximum):
        transport = httpx.ASGITransport(app=MultipartBodyLimit(self.app, maximum=maximum))
        return httpx.AsyncClient(transport=transport, base_url="http://localhost")

    def track_files(self):
        recorded = {"body": [], "parts": []}
        stack = self.enterContext(ExitStack())
        for name, target, factory in [
            ("body", "app.workspace_http_common.TemporaryFile", TemporaryFile),
            ("parts", "starlette.formparsers.SpooledTemporaryFile", SpooledTemporaryFile),
        ]:
            def track(*args, factory=factory, name=name, **kwargs):
                file = factory(*args, **kwargs)
                recorded[name].append(file)
                return file
            stack.enter_context(patch(target, side_effect=track))
        return recorded

    async def chunks(self, content):
        for offset in range(0, len(content), 59):
            yield content[offset:offset + 59]

    async def test_exact_limit_chunked_preserves_four_files_and_closes_every_spool(self):
        opened = self.track_files()
        response = await self.client.post("/api/test", headers=self.headers, content=self.chunks(self.body))
        self.assertNotIn("content-length", response.request.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"note": "Example case", "contents": [
            [role + ".pdf", "Example " + role] for role in ("bill", "letter", "records", "summary")]})
        self.assertEqual([len(opened["body"]), len(opened["parts"])], [1, 4])
        self.assertTrue(all(file.closed for files in opened.values() for file in files))

    async def test_large_file_content_survives_multiple_replay_blocks(self):
        bill = b"Practice bill line\n" * 8000
        body = self.body.replace(b"Example bill", bill)
        async with self.limited_client(len(body)) as client:
            response = await client.post("/api/test", headers=self.headers, content=body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["contents"][0], ["bill.pdf", bill.decode()])

    async def test_oversize_declared_before_body_and_chunked_before_parser(self):
        opened = self.track_files()
        content = packet() + b"\r\n"
        yielded = []

        async def counted():
            async for part in self.chunks(content):
                yielded.append(len(part))
                yield part

        declared = await self.client.post("/api/test", headers=self.headers | {"Content-Length": str(len(content))},
                                          content=counted())
        self.assertEqual(declared.status_code, 413)
        self.assertEqual(yielded, [])
        self.assertEqual(opened, {"body": [], "parts": []})
        with patch("starlette.requests.MultiPartParser", side_effect=AssertionError("Parsed oversized upload")):
            chunked = await self.client.post("/api/test", headers=self.headers, content=counted())
        self.assertEqual(chunked.status_code, 413)
        self.assertGreater(len(yielded), 1)
        self.assertEqual(len(opened["body"]), 1)
        self.assertTrue(opened["body"][0].closed)

    async def test_fastapi_validation_keeps_its_normal_cleanup(self):
        opened = self.track_files()
        response = await self.client.post("/api/test", headers=self.headers, content=packet(note=False))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(len(opened["parts"]), 4)
        self.assertTrue(all(file.closed for files in opened.values() for file in files))

    async def test_disconnect_closes_spool_before_parsing(self):
        opened = self.track_files()
        messages = iter([{"type": "http.request", "body": self.body[:100], "more_body": True},
                         {"type": "http.disconnect"}])

        async def receive():
            return next(messages)

        async def send(message):
            pass

        scope = {"type": "http", "headers": [(b"content-type", b"multipart/form-data; boundary=demo")]}
        await MultipartBodyLimit(self.app, maximum=len(self.body))(scope, receive, send)
        self.assertEqual(len(opened["parts"]), 0)
        self.assertTrue(opened["body"][0].closed)

    def test_production_allowance_covers_four_maximum_pdfs(self):
        self.assertEqual(MAX_MULTIPART_BYTES, 4 * INTAKE_BYTES + 1024 * 1024)
