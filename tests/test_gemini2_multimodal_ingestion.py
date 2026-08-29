import os
import sys
import json
import base64
import unittest
from unittest.mock import patch
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gigamind.services.parser import extract_text_from_file
from gigamind.services.indexing import (
    index_file_content,
    delete_storage_file_index,
    list_indexed_storage_files,
    get_file_chunks
)
from gigamind.db.database import init_db, Session, engine, StorageFileItem, StorageChunkItem, select
from gigamind.services.memory import add_memory, search_memory, delete_memory
from fastapi.testclient import TestClient
from gigamind.main import app, API_KEY
from tests.cleanup_test_data import cleanup_all_test_data


class TestGemini2MultimodalIngestion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cleanup_all_test_data(verbose=False)
        cls.client = TestClient(app)
        cls.auth_headers = {"Authorization": f"Bearer {API_KEY}"}

    @classmethod
    def tearDownClass(cls):
        cleanup_all_test_data(verbose=False)

    def setUp(self):
        self.created_mem_ids = []
        self.created_file_keys = []

    def tearDown(self):
        for mem_id in self.created_mem_ids:
            try:
                delete_memory(mem_id)
            except Exception:
                pass
        for file_key in self.created_file_keys:
            try:
                delete_storage_file_index(file_key)
            except Exception:
                pass
        self.created_mem_ids.clear()
        self.created_file_keys.clear()

    def test_01_direct_pdf_binary_ingestion(self):
        # Create minimal PDF binary payload
        minimal_pdf = (
            b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
            b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>/Contents 4 0 R>>endobj\n"
            b"4 0 obj<</Length 55>>stream\n"
            b"BT /F1 12 Tf 100 700 Td (Quantum Teleportation Multimodal Benchmark) Tj ET\n"
            b"endstream\nendobj\nxref\n0 5\n0000000000 65535 f \n"
            b"0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000216 00000 n \n"
            b"trailer<</Size 5/Root 1 0 R>>\nstartxref\n320\n%%EOF"
        )
        pdf_key = "files/test/2026/08/quantum_teleportation.pdf"
        self.created_file_keys.append(pdf_key)

        res = index_file_content(
            file_key=pdf_key,
            filename="quantum_teleportation.pdf",
            data=minimal_pdf,
            mime_type="application/pdf",
            source_agent="test_runner"
        )
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["multimodal_type"], "pdf")

        # Verify whole-document embedding saved in Neon
        with Session(engine) as session:
            f_item = session.exec(select(StorageFileItem).where(StorageFileItem.key == pdf_key)).first()
            self.assertIsNotNone(f_item)
            self.assertEqual(f_item.multimodal_type, "pdf")
            self.assertTrue(len(json.loads(f_item.embedding_json)) > 0)

    def test_02_multimodal_image_diagram_ingestion(self):
        tiny_png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        )
        img_key = "files/test/2026/08/transmon_circuit_schematic.png"
        self.created_file_keys.append(img_key)

        res = index_file_content(
            file_key=img_key,
            filename="transmon_circuit_schematic.png",
            data=tiny_png_bytes,
            mime_type="image/png",
            source_agent="test_runner"
        )
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["multimodal_type"], "image")

        # Search specifically for visual diagram
        search_res = search_memory("transmon circuit schematic diagram", limit=5, scope="files")
        filenames = [r["filename"] for r in search_res]
        self.assertIn("transmon_circuit_schematic.png", filenames)
        top_match = next(r for r in search_res if r["filename"] == "transmon_circuit_schematic.png")
        self.assertGreater(top_match["score"], 0.3)

    def test_03_hierarchical_dual_level_search_fusion(self):
        doc_key = "files/test/2026/08/surface_code_architecture.md"
        self.created_file_keys.append(doc_key)

        content = (
            "# Fault-Tolerant Surface Codes\n\n"
            "Surface code quantum error correction requires a 2D square lattice of data and syndrome physical qubits. "
            "Threshold calculations demonstrate fault tolerance at 0.7% physical gate error rates."
        )
        index_file_content(
            file_key=doc_key,
            filename="surface_code_architecture.md",
            data=content.encode("utf-8"),
            mime_type="text/markdown",
            source_agent="test_runner"
        )

        mem = add_memory(
            content="User prefers rotated surface code topologies over heavy-hex layouts for cryo-CMOS scaling.",
            category="test_suite",
            source_agent="test_runner",
            tags=["test_runner"]
        )
        self.created_mem_ids.append(mem["id"])

        # Unified search across all knowledge
        res = search_memory("surface code error correction physical qubits", limit=5, scope="all")
        sources = {r.get("source") for r in res}
        self.assertIn("file", sources)
        self.assertIn("memory", sources)

    def test_04_rest_search_multimodal_endpoint(self):
        payload = {
            "query": "quantum teleportation and circuit schematic",
            "scope": "files",
            "limit": 3
        }
        res = self.client.post("/api/v1/search_multimodal", json=payload, headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["scope"], "files")
        self.assertIn("results", data)

    def test_05_fastmcp_multimodal_tools(self):
        req = {
            "jsonrpc": "2.0",
            "id": 100,
            "method": "tools/call",
            "params": {
                "name": "search_multimodal",
                "arguments": {
                    "query": "quantum fault tolerance",
                    "scope": "all",
                    "limit": 3
                }
            }
        }
        res = self.client.post("/messages", json=req)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("result", data)
        self.assertIn("content", data["result"])


if __name__ == "__main__":
    unittest.main()
