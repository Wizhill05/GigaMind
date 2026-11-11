"""Bounded, loss-aware source parsing for file indexing."""

import io
import os

import pypdf

MAX_FILE_BYTES = 20_000_000
MAX_EXTRACT_CHARS = 500_000
MAX_PDF_PAGES = 100
MAX_INLINE_BYTES = 10_000_000

TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".tsv",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".env",
    ".xml",
    ".html",
    ".css",
    ".scss",
    ".sql",
    ".py",
    ".ts",
    ".js",
    ".tsx",
    ".jsx",
    ".rs",
    ".go",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".java",
    ".kt",
    ".rb",
    ".php",
    ".sh",
    ".bash",
    ".zsh",
    ".bat",
    ".cmd",
    ".ps1",
    ".r",
    ".lua",
    ".swift",
    ".dart",
    ".dockerfile",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

BINARY_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".ogg",
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".zip",
    ".tar",
    ".gz",
    ".7z",
    ".rar",
    ".exe",
    ".bin",
    ".iso",
    ".dll",
    ".so",
}


def _unsupported(reason, format_tag="binary"):
    return {
        "supported": False,
        "format": format_tag,
        "text": "",
        "pages": [],
        "char_count": 0,
        "truncated": False,
        "error": reason,
    }


def binary_mime(data):
    """Recognize supported binary signatures; provider still validates image decoding."""
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


def extract_text_from_file(data, filename, mime_type=None):
    if not isinstance(data, bytes):
        raise ValueError("File data must be bytes")
    if not data:
        return _unsupported("File is empty", "empty")
    if len(data) > MAX_FILE_BYTES:
        return _unsupported("File exceeds the application byte limit")
    ext = os.path.splitext(filename or "")[1].lower()
    declared = (mime_type or "").partition(";")[0].strip().lower()
    generic = {"", "application/octet-stream"}
    detected = binary_mime(data)
    expected = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }.get(ext)
    if detected:
        if (declared not in generic and declared != detected) or (
            expected and expected != detected
        ):
            return _unsupported("File signature conflicts with its declared type")
        if ext in TEXT_EXTENSIONS or (
            ext in IMAGE_EXTENSIONS and detected == "application/pdf"
        ):
            return _unsupported("File signature conflicts with its filename")
        if detected == "application/pdf":
            return _extract_pdf(data, filename)
        if len(data) > MAX_INLINE_BYTES:
            return _unsupported("Image exceeds the application inline limit")
        text = f"Image artifact: {filename}"
        return {
            "supported": True,
            "format": "image",
            "text": text,
            "pages": [{"page_number": 1, "text": text}],
            "raw_bytes": data,
            "mime_type": detected,
            "char_count": 0,
            "truncated": False,
        }
    if (
        ext == ".pdf"
        or ext in IMAGE_EXTENSIONS
        or declared == "application/pdf"
        or declared.startswith("image/")
    ):
        return _unsupported("Unsupported or invalid binary file signature")
    if ext in BINARY_EXTENSIONS:
        return _unsupported("Unsupported file type")
    text_mime = declared.startswith("text/") or declared in {
        "application/json",
        "application/xml",
        "application/javascript",
        "application/yaml",
    }
    if not (ext in TEXT_EXTENSIONS or text_mime) or (
        declared not in generic and not text_mime
    ):
        return _unsupported("Unsupported file type")
    try:
        decoded = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return _unsupported("Text must use UTF-8 encoding")
    if "\x00" in decoded:
        return _unsupported("Binary content cannot be indexed as text")
    cleaned = decoded.strip()
    if len(cleaned) > MAX_EXTRACT_CHARS:
        return _unsupported("Text exceeds the application extraction limit")
    if not cleaned:
        return _unsupported("File contains no text", "empty")
    format_tag = (
        "markdown"
        if ext in {".md", ".markdown"}
        else ("code" if ext in {".py", ".ts", ".js", ".sql", ".rs", ".go"} else "text")
    )
    return {
        "supported": True,
        "format": format_tag,
        "text": cleaned,
        "pages": [{"page_number": 1, "text": cleaned}],
        "char_count": len(cleaned),
        "mime_type": declared if text_mime else "text/plain",
        "truncated": False,
    }


def _extract_pdf(data, filename):
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        if reader.is_encrypted or not 1 <= len(reader.pages) <= MAX_PDF_PAGES:
            return _unsupported(
                "PDF is encrypted or exceeds the application page limit"
            )
        pages = []
        texts = []
        total_chars = 0
        total_page_bytes = 0
        for number, page in enumerate(reader.pages, 1):
            # Extraction failures reject this attempt rather than hiding missing pages.
            page_text = (page.extract_text() or "").strip()
            total_chars += len(page_text)
            if total_chars > MAX_EXTRACT_CHARS:
                return _unsupported("PDF exceeds the application extraction limit")
            writer = pypdf.PdfWriter()
            writer.add_page(page)
            output = io.BytesIO()
            writer.write(output)
            page_bytes = output.getvalue()
            total_page_bytes += len(page_bytes)
            if (
                len(page_bytes) > MAX_INLINE_BYTES
                or total_page_bytes > MAX_FILE_BYTES * 2
            ):
                return _unsupported("PDF exceeds the application page-byte limit")
            pages.append(
                {"page_number": number, "text": page_text, "raw_bytes": page_bytes}
            )
            if page_text:
                texts.append(f"--- [Page {number}] ---\n{page_text}")
        text = "\n\n".join(texts)
        return {
            "supported": True,
            "format": "pdf",
            "text": text or f"PDF document: {filename}",
            "pages": pages,
            "char_count": total_chars,
            "mime_type": "application/pdf",
            "truncated": False,
        }
    except Exception:
        return _unsupported("PDF could not be parsed completely")
