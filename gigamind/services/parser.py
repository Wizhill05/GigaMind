import io
import os
import base64
import mimetypes
from typing import Optional, Dict, Any, List
try:
    import pypdf
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False


MAX_EXTRACT_CHARS = 500000  # Cap extraction to ~100 pages to protect 512MB RAM constraint

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".env", ".xml", ".html", ".css", ".scss", ".sql",
    ".py", ".ts", ".js", ".tsx", ".jsx", ".rs", ".go", ".c", ".cpp",
    ".h", ".hpp", ".java", ".kt", ".rb", ".php", ".sh", ".bash", ".zsh",
    ".bat", ".cmd", ".ps1", ".r", ".lua", ".swift", ".dart", ".dockerfile"
}

IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"
}

BINARY_EXTENSIONS = {
    ".mp3", ".wav", ".ogg", ".mp4", ".mov", ".avi", ".mkv", ".zip",
    ".tar", ".gz", ".7z", ".rar", ".exe", ".bin", ".iso", ".dll", ".so"
}


def extract_text_from_file(
    data: bytes,
    filename: str,
    mime_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    Extracts text and page structure from an uploaded binary payload.
    Supports PDF, Markdown, code, plain text, and CSV formats.
    """
    if not data:
        return {
            "supported": False,
            "format": "empty",
            "text": "",
            "pages": [],
            "char_count": 0,
            "truncated": False
        }

    ext = os.path.splitext(filename or "")[1].lower()
    if not mime_type:
        mime_type, _ = mimetypes.guess_type(filename)
    mime_type = (mime_type or "").lower()

    # 1. PDF Extraction
    if ext == ".pdf" or "application/pdf" in mime_type:
        if not PYPDF_AVAILABLE:
            return {
                "supported": False,
                "format": "pdf",
                "text": "",
                "pages": [],
                "char_count": 0,
                "truncated": False,
                "error": "pypdf library not available"
            }
        try:
            reader = pypdf.PdfReader(io.BytesIO(data))
            pages_extracted: List[Dict[str, Any]] = []
            full_text_chunks: List[str] = []
            total_chars = 0
            truncated = False

            for idx, page in enumerate(reader.pages):
                page_num = idx + 1
                try:
                    p_text = (page.extract_text() or "").strip()
                except Exception:
                    p_text = ""

                if p_text:
                    if total_chars + len(p_text) > MAX_EXTRACT_CHARS:
                        remaining = MAX_EXTRACT_CHARS - total_chars
                        p_text = p_text[:remaining]
                        truncated = True

                    pages_extracted.append({"page_number": page_num, "text": p_text})
                    full_text_chunks.append(f"--- [Page {page_num}] ---\n{p_text}")
                    total_chars += len(p_text)

                if truncated or total_chars >= MAX_EXTRACT_CHARS:
                    truncated = True
                    break

            combined_text = "\n\n".join(full_text_chunks).strip()
            return {
                "supported": True,
                "format": "pdf",
                "text": combined_text or f"[PDF Document: {filename}]",
                "pages": pages_extracted,
                "raw_bytes": data,
                "char_count": len(combined_text),
                "truncated": truncated
            }
        except Exception as e:
            return {
                "supported": True,
                "format": "pdf",
                "text": f"[PDF Document: {filename}]",
                "pages": [{"page_number": 1, "text": f"[PDF: {filename}]"}],
                "raw_bytes": data,
                "char_count": 0,
                "truncated": False
            }

    # 2. Multimodal Image Parsing (PNG, JPG, WEBP, GIF, BMP)
    if ext in IMAGE_EXTENSIONS or (mime_type and mime_type.startswith("image/")):
        try:
            img_b64 = base64.b64encode(data).decode("utf-8")
            clean_name = filename.replace("_", " ").replace("-", " ")
            return {
                "supported": True,
                "format": "image",
                "text": f"[Image Artifact: {clean_name}]",
                "image_base64": img_b64,
                "raw_bytes": data,
                "mime_type": mime_type or "image/png",
                "pages": [{"page_number": 1, "text": f"Image artifact: {clean_name}", "image_base64": img_b64}],
                "char_count": len(clean_name),
                "truncated": False
            }
        except Exception as img_err:
            print(f"Image base64 encoding note: {img_err}")
    # 3. Binary / Media Bypass (Audio, Video, Archives, Executables)
    if ext in BINARY_EXTENSIONS or any(b in mime_type for b in ["audio/", "video/", "application/zip", "application/octet-stream"]) and ext not in TEXT_EXTENSIONS:
        return {
            "supported": False,
            "format": "binary",
            "text": "",
            "pages": [],
            "char_count": 0,
            "truncated": False
        }

    # 3. Plaintext, Markdown, Code, CSV Extraction
    try:
        try:
            decoded_text = data.decode("utf-8")
        except UnicodeDecodeError:
            try:
                decoded_text = data.decode("latin-1")
            except Exception:
                decoded_text = data.decode("utf-8", errors="replace")

        cleaned = decoded_text.strip()
        truncated = False
        if len(cleaned) > MAX_EXTRACT_CHARS:
            cleaned = cleaned[:MAX_EXTRACT_CHARS]
            truncated = True

        format_tag = "markdown" if ext in [".md", ".markdown"] else ("code" if ext in [".py", ".ts", ".js", ".sql", ".rs", ".go"] else "text")

        return {
            "supported": bool(cleaned),
            "format": format_tag,
            "text": cleaned,
            "pages": [{"page_number": 1, "text": cleaned}],
            "char_count": len(cleaned),
            "truncated": truncated
        }
    except Exception as e:
        return {
            "supported": False,
            "format": "unknown",
            "text": "",
            "pages": [],
            "char_count": 0,
            "truncated": False,
            "error": str(e)
        }
