"""Provider wire contracts and real parsing/publication; external boundaries only are stubbed."""

import base64
import io
import json
import urllib.error

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from sqlmodel import Session, SQLModel, create_engine, select

from gigamind.db.database import StorageChunkItem, StorageFileItem
from gigamind.services import embedding, indexing, jobs, parser

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a7S8AAAAASUVORK5CYII="
)


@pytest.fixture
def wire(monkeypatch):
    monkeypatch.setattr(embedding, "_get_api_keys", lambda: ["test-secret"])
    monkeypatch.setattr(embedding, "DEFAULT_DIM", 3)
    monkeypatch.setattr(embedding.time, "sleep", lambda _: None)
    state = {"body": {"embedding": {"values": [1, 2, 3]}}, "requests": []}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, maximum):
            body = state["body"]
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            return raw[:maximum]

    def send(request, timeout):
        assert timeout == 20
        state["requests"].append(request)
        return Response()

    monkeypatch.setattr(embedding.urllib.request, "urlopen", send)
    return state


def test_text_and_image_wire_contract(wire):
    assert embedding.generate_embedding(text="hello") == [1, 2, 3]
    req = wire["requests"][-1]
    payload = json.loads(req.data)
    assert payload == {
        "model": embedding.MODEL_NAME,
        "content": {"parts": [{"text": "hello"}]},
        "output_dimensionality": 3,
    }
    assert req.full_url.endswith(":embedContent")
    assert "test-secret" not in req.full_url
    assert req.get_header("X-goog-api-key") == "test-secret"
    embedding.generate_embedding(inline_bytes=PNG, mime_type="image/png")
    part = json.loads(wire["requests"][-1].data)["content"]["parts"][0]
    assert part == {
        "inline_data": {
            "mime_type": "image/png",
            "data": base64.b64encode(PNG).decode(),
        }
    }
    embedding.generate_embedding(image_base64=base64.b64encode(PNG).decode())
    assert json.loads(wire["requests"][-1].data)["content"]["parts"] == [part]


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        [],
        {"embedding": None},
        {"embedding": {"values": None}},
        *[
            {"embedding": {"values": v}}
            for v in (
                [],
                [1, 2],
                [1, 2, 3, 4],
                [True, 2, 3],
                ["1", 2, 3],
                [0, 0, 0],
                [1, float("nan"), 3],
                [1, float("inf"), 3],
                [10**400, 2, 3],
                {"0": 1, "1": 2, "2": 3},
            )
        ],
        b"invalid json",
        b"x" * (embedding.MAX_RESPONSE_BYTES + 1),
    ],
)
def test_invalid_provider_response_is_rejected_without_retry_or_secret(wire, body):
    wire["body"] = body
    with pytest.raises(RuntimeError, match="invalid response") as err:
        embedding.generate_embedding(text="hello")
    assert "test-secret" not in str(err.value)
    assert len(wire["requests"]) == 1


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"text": ""},
        {"text": " "},
        {"text": "\u2603" * 3000},
        {"inline_bytes": b""},
        {"inline_bytes": PNG, "mime_type": "application/pdf"},
        {"inline_bytes": b"not png", "mime_type": "image/png"},
        {"inline_bytes": PNG, "image_base64": "abc"},
        {"image_base64": "!!!!"},
        {
            "inline_bytes": b"x" * (parser.MAX_INLINE_BYTES + 1),
            "mime_type": "image/png",
        },
    ],
)
def test_invalid_input_never_reaches_provider(wire, arguments):
    with pytest.raises(ValueError):
        embedding.generate_embedding(**arguments)
    assert wire["requests"] == []


def test_http_error_does_not_echo_url_key_or_body(wire, monkeypatch):
    def send(*args, **kwargs):
        raise urllib.error.HTTPError(
            "https://example.invalid/?key=test-secret",
            400,
            "test-secret",
            {},
            io.BytesIO(b"test-secret"),
        )

    monkeypatch.setattr(embedding.urllib.request, "urlopen", send)
    with pytest.raises(RuntimeError, match="HTTP 400") as err:
        embedding.generate_embedding(text="hello")
    assert "test-secret" not in str(err.value)
    assert err.value.__suppress_context__


def pdf_bytes(pages=9, text_page=9):
    writer = PdfWriter()
    for number in range(1, pages + 1):
        page = writer.add_blank_page(width=200, height=200)
        if number == text_page:
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
            )
            stream = DecodedStreamObject()
            stream.set_data(
                b"BT /F1 12 Tf 10 100 Td (Late source fact: comet engine) Tj ET"
            )
            page[NameObject("/Contents")] = writer._add_object(stream)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.fixture
def pipeline(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'payload.db'}")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(indexing, "engine", engine)
    monkeypatch.setattr(indexing, "is_postgres", False)
    monkeypatch.setattr(embedding, "DEFAULT_DIM", 3)
    yield engine
    engine.dispose()


def test_every_pdf_page_and_late_text_are_submitted_with_exact_provenance(
    pipeline, wire
):
    result = indexing.index_file_content("files/archive", "report.pdf", pdf_bytes())
    assert result["status"] == "completed"
    requests = [json.loads(req.data)["content"]["parts"] for req in wire["requests"]]
    pdfs = [
        base64.b64decode(parts[0]["inline_data"]["data"])
        for parts in requests
        if "inline_data" in parts[0]
    ]
    assert len(pdfs) == 9
    assert all(len(PdfReader(io.BytesIO(data)).pages) == 1 for data in pdfs)
    assert "comet engine" in PdfReader(io.BytesIO(pdfs[-1])).pages[0].extract_text()
    assert any("comet engine" in parts[0].get("text", "") for parts in requests)
    with Session(pipeline) as session:
        chunks = session.exec(
            select(StorageChunkItem).order_by(StorageChunkItem.chunk_index)
        ).all()
        assert [
            chunk.page_number for chunk in chunks if chunk.is_visual_anchor
        ] == list(range(1, 10))
        assert [
            (chunk.page_number, chunk.content)
            for chunk in chunks
            if not chunk.is_visual_anchor
        ] == [(9, "Late source fact: comet engine")]
        assert (
            session.exec(select(StorageFileItem)).one().mime_type == "application/pdf"
        )
    assert indexing.get_file_chunks("files/archive")[-1]["is_visual_anchor"] is False


def test_queued_reindex_preserves_source_name_and_infers_correct_mime(
    pipeline, wire, monkeypatch
):
    monkeypatch.setattr(indexing.storage_service, "is_enabled", lambda: True)
    monkeypatch.setattr(
        indexing.storage_service,
        "download_file",
        lambda key: b"queued source: comet engine",
    )
    indexing.register_storage_file("files/opaque-key", "notes.txt", "text/plain")
    job = jobs.enqueue("index_file", {"key": "files/opaque-key"}, engine=pipeline)
    assert jobs.run_once(engine=pipeline).state == "completed"
    assert jobs.status(job.id, engine=pipeline).state == "completed"
    with Session(pipeline) as session:
        stored = session.exec(select(StorageFileItem)).one()
        assert stored.filename == "notes.txt" and stored.mime_type == "text/plain"
        assert (
            session.exec(select(StorageChunkItem)).one().content
            == "queued source: comet engine"
        )
    assert all(
        "text" in part
        for req in wire["requests"]
        for part in json.loads(req.data)["content"]["parts"]
    )
    monkeypatch.setattr(indexing.storage_service, "download_file", lambda key: PNG)
    indexing.register_storage_file("files/image-key", "diagram.png", "image/png")
    jobs.enqueue("index_file", {"key": "files/image-key"}, engine=pipeline)
    assert jobs.run_once(engine=pipeline).state == "completed"
    assert (
        json.loads(wire["requests"][-1].data)["content"]["parts"][0]["inline_data"][
            "mime_type"
        ]
        == "image/png"
    )


@pytest.mark.parametrize(
    "data,name,mime",
    [
        (PNG, "image.pdf", None),
        (PNG, "image.png", "image/jpeg"),
        (pdf_bytes(1, 1), "image.png", None),
        (b"not pdf", "report.pdf", "application/pdf"),
        (b"\xff\xfe binary", "readme.txt", "text/plain"),
        (b"abc\x00def", "readme.txt", None),
        (b"GIF89a", "photo.gif", None),
        (b"unknown", "unknown.bin", "text/plain"),
    ],
)
def test_signature_type_and_utf8_mismatch_are_explicitly_unsupported(data, name, mime):
    result = parser.extract_text_from_file(data, name, mime)
    assert not result["supported"] and result["error"] and not result["truncated"]


def test_limits_and_invalid_pdf_do_not_silently_truncate(wire, monkeypatch):
    with pytest.raises(ValueError, match="one to six"):
        embedding.generate_embedding(
            inline_bytes=pdf_bytes(7, None), mime_type="application/pdf"
        )
    monkeypatch.setattr(parser, "MAX_PDF_PAGES", 2)
    assert not parser.extract_text_from_file(pdf_bytes(3, None), "report.pdf")[
        "supported"
    ]
    monkeypatch.setattr(parser, "MAX_EXTRACT_CHARS", 3)
    assert not parser.extract_text_from_file(b"long text", "notes.txt")["supported"]
    assert not parser.extract_text_from_file(pdf_bytes(1, 1), "report.pdf")["supported"]
    assert not parser.extract_text_from_file(b"%PDF-corrupt", "report.pdf")["supported"]
    assert not wire["requests"]


def test_pdf_replacement_guard_preserves_all_previous_chunks(pipeline, wire):
    indexing.index_file_content("key", "notes.txt", b"old source")
    with Session(pipeline) as session:
        before = session.exec(select(StorageChunkItem)).one().model_dump()

    def deny(session):
        session.exec(select(StorageFileItem)).one().source_agent = "must roll back"
        raise jobs.PermanentFailure("stale lease")

    with pytest.raises(jobs.PermanentFailure, match="stale lease"):
        indexing.index_file_content(
            "key", "report.pdf", pdf_bytes(), publication_guard=deny
        )
    with Session(pipeline) as session:
        assert session.exec(select(StorageChunkItem)).one().model_dump() == before
        assert session.exec(select(StorageFileItem)).one().source_agent == "user"


def test_forbidden_key_rotates_to_configured_alternative(wire, monkeypatch):
    monkeypatch.setattr(embedding, "_get_api_keys", lambda: ["bad-key", "good-key"])
    monkeypatch.setattr(embedding, "key_pool", embedding.GeminiKeyPool())
    succeed = embedding.urllib.request.urlopen
    attempted = []

    def send(request, timeout):
        key = request.get_header("X-goog-api-key")
        attempted.append(key)
        if key == "bad-key":
            raise urllib.error.HTTPError(
                request.full_url, 403, "forbidden", {}, io.BytesIO(b"bad-key")
            )
        return succeed(request, timeout)

    monkeypatch.setattr(embedding.urllib.request, "urlopen", send)
    assert embedding.generate_embedding(text="hello") == [1, 2, 3]
    assert attempted == ["bad-key", "good-key"]
