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
    reindex_storage_file_by_key,
    delete_storage_file_index,
    list_indexed_storage_files
)
from gigamind.db.database import init_db, Session, engine, StorageFileItem, StorageChunkItem, select
from gigamind.services.memory import add_memory, search_memory, delete_memory
from fastapi.testclient import TestClient
from gigamind.main import app, API_KEY
from tests.cleanup_test_data import cleanup_all_test_data


class TestVectorizedStorageSearch(unittest.TestCase):
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

    def test_01_parser_extract_text(self):
        # 1. Plain text extraction
        res_txt = extract_text_from_file(b"Neural quantum state simulation", "quantum.txt")
        self.assertTrue(res_txt["supported"])
        self.assertEqual(res_txt["format"], "text")
        self.assertIn("quantum state", res_txt["text"])

        # 2. Markdown extraction
        res_md = extract_text_from_file(b"# Quantum Algorithm\n\nOptimized QAOA on 128 qubits.", "algo.md")
        self.assertTrue(res_md["supported"])
        self.assertEqual(res_md["format"], "markdown")
        self.assertIn("QAOA", res_md["text"])

        # 3. Code extraction
        res_code = extract_text_from_file(b"def simulate_hamiltonian(n: int):\n    return np.eye(n)", "sim.py")
        self.assertTrue(res_code["supported"])
        self.assertEqual(res_code["format"], "code")
        self.assertIn("simulate_hamiltonian", res_code["text"])

        # 4. Binary bypass
        res_bin = extract_text_from_file(b"\x89PNG\r\n\x1a\n\x00\x00", "diagram.png")
        self.assertFalse(res_bin["supported"])
        self.assertEqual(res_bin["format"], "binary")

    def test_02_indexing_file_pipeline(self):
        file_key = "files/test/2026/08/test_paper.md"
        self.created_file_keys.append(file_key)

        content = (
            "# Superconducting Qubits & Error Mitigation\n\n"
            "This paper explores dynamic decoupling sequences to prolong T2 coherence time in transmon qubits. "
            "Our benchmarking across 64 physical qubits demonstrated a 3.2x reduction in decoherence rates.\n\n"
            "## Experimental Results\n"
            "Measurements conducted at 15 millikelvin confirmed the fidelity improvements over baseline calibration."
        )

        idx_res = index_file_content(
            file_key=file_key,
            filename="test_paper.md",
            data=content.encode("utf-8"),
            mime_type="text/markdown",
            source_agent="test_runner"
        )

        self.assertEqual(idx_res["status"], "completed")
        self.assertGreater(idx_res["chunks_created"], 0)

        # Verify DB entries
        with Session(engine) as session:
            f_item = session.exec(select(StorageFileItem).where(StorageFileItem.key == file_key)).first()
            self.assertIsNotNone(f_item)
            self.assertEqual(f_item.filename, "test_paper.md")
            self.assertEqual(f_item.indexing_status, "completed")

            chunks = session.exec(select(StorageChunkItem).where(StorageChunkItem.file_key == file_key)).all()
            self.assertGreater(len(chunks), 0)
            self.assertIn("Superconducting Qubits", chunks[0].content)

    def test_03_scope_search_behavior(self):
        # 1. Ingest a textual memory with test_runner agent
        mem = add_memory(
            content="User personal note: prefers superconducting transmon architectures over trapped ions for lab experiments.",
            category="test_suite",
            source_agent="test_runner",
            tags=["test_runner", "hardware", "qubits"]
        )
        mem_id = mem["id"]
        self.created_mem_ids.append(mem_id)

        # 2. Ingest an R2 file document
        doc_key = "files/test/2026/08/trapped_ion_study.md"
        self.created_file_keys.append(doc_key)

        doc_content = (
            "# Trapped-Ion Quantum Computing Whitepaper\n\n"
            "Trapped ion systems achieve 99.9% two-qubit gate fidelity using ytterbium-171 ions. "
            "However, shuttling speed limitations introduce latency in deep quantum circuits."
        )
        index_file_content(
            file_key=doc_key,
            filename="trapped_ion_study.md",
            data=doc_content.encode("utf-8"),
            mime_type="text/markdown",
            source_agent="test_runner"
        )

        # Query 1: scope="all" (Default) -> Should retrieve matches from both memories and files
        res_all = search_memory("quantum architectures fidelity and transmon", limit=10, scope="all")
        sources_all = {r.get("source") for r in res_all}
        self.assertIn("memory", sources_all, "scope=all must include memories")
        self.assertIn("file", sources_all, "scope=all must include file chunks")

        # Check citation presence on file chunk
        file_matches = [r for r in res_all if r.get("source") == "file"]
        self.assertTrue(len(file_matches) > 0)
        self.assertIn("filename", file_matches[0])
        self.assertIn("citation", file_matches[0])

        # Query 2: scope="memories" -> Must return only memories, 0 files
        res_mem = search_memory("quantum architectures fidelity and transmon", limit=10, scope="memories")
        for r in res_mem:
            self.assertNotEqual(r.get("source"), "file", "scope=memories must not return file chunks")

        # Query 3: scope="files" -> Must return only file chunks, 0 memories
        res_files = search_memory("trapped ion ytterbium fidelity", limit=10, scope="files")
        for r in res_files:
            self.assertEqual(r.get("source"), "file", "scope=files must return only file chunks")
            self.assertIn("trapped_ion_study.md", r.get("filename", ""))

    def test_04_fastapi_rest_endpoints(self):
        doc_key = "files/test/2026/08/api_test_doc.txt"
        self.created_file_keys.append(doc_key)

        file_payload = {
            "filename": "api_test_doc.txt",
            "content_base64": base64.b64encode(b"FastAPI R2 Vectorized Storage Integration Content").decode("utf-8"),
            "mime_type": "text/plain"
        }

        # Mock storage_service.upload_file so test runs without needing live AWS credentials
        with patch("gigamind.main.storage_service.is_enabled", return_value=True), \
             patch("gigamind.main.storage_service.upload_file", return_value={"key": doc_key, "filename": "api_test_doc.txt", "size_bytes": 50}):
            up_res = self.client.post("/api/v1/files/upload_base64", json=file_payload, headers=self.auth_headers)
            self.assertEqual(up_res.status_code, 200)
            self.assertTrue(up_res.json()["success"])

        # Directly index the content for immediate search test
        index_file_content(file_key=doc_key, filename="api_test_doc.txt", data=b"FastAPI R2 Vectorized Storage Integration Content", source_agent="test_runner")

        # 2. Test search_memory with scope
        search_payload = {"query": "Vectorized Storage Integration", "scope": "files", "limit": 3}
        s_res = self.client.post("/api/v1/search_memory", json=search_payload, headers=self.auth_headers)
        self.assertEqual(s_res.status_code, 200)
        data = s_res.json()
        self.assertEqual(data["scope"], "files")
        self.assertTrue(len(data["results"]) > 0)
        self.assertEqual(data["results"][0]["source"], "file")

        # 3. Test dedicated /api/v1/search_files endpoint
        f_search_res = self.client.post("/api/v1/search_files", json={"query": "FastAPI Vectorized", "limit": 3}, headers=self.auth_headers)
        self.assertEqual(f_search_res.status_code, 200)
        f_data = f_search_res.json()
        self.assertEqual(f_data["scope"], "files")
        self.assertTrue(len(f_data["results"]) > 0)

        # 4. Test /api/v1/files/indexed
        idx_list_res = self.client.get("/api/v1/files/indexed", headers=self.auth_headers)
        self.assertEqual(idx_list_res.status_code, 200)
        indexed_files = idx_list_res.json()["files"]
        self.assertTrue(any(f["key"] == doc_key for f in indexed_files))

    def test_05_fastmcp_tools(self):
        file_key = "files/test/2026/08/mcp_doc.txt"
        self.created_file_keys.append(file_key)

        index_file_content(file_key=file_key, filename="mcp_doc.txt", data=b"FastMCP Knowledge Search Tool Verification", source_agent="test_runner")

        # Call search_file_storage via FastMCP JSON-RPC
        rpc_call = {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "search_file_storage",
                "arguments": {
                    "query": "FastMCP Knowledge Verification",
                    "limit": 3
                }
            }
        }
        rpc_res = self.client.post("/messages", json=rpc_call)
        self.assertEqual(rpc_res.status_code, 200)
        data = rpc_res.json()
        content_str = data["result"]["content"][0]["text"]
        parsed_result = json.loads(content_str)
        self.assertEqual(parsed_result["scope"], "files")
        self.assertTrue(len(parsed_result["results"]) > 0)
        self.assertEqual(parsed_result["results"][0]["source"], "file")


if __name__ == "__main__":
    unittest.main()
