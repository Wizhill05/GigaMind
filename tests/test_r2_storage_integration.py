import os
import sys
import json
import base64
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gigamind.services.storage import sanitize_filename, StorageService
from gigamind.db.database import init_db, Session, engine, MemoryItem, select
from gigamind.services.memory import (
    add_memory,
    search_memory,
    get_memories,
    update_memory,
    delete_memory,
    reset_all_memories,
    export_all_memories,
    _hydrate_attachments
)
from fastapi.testclient import TestClient
from gigamind.main import app, API_KEY
from tests.cleanup_test_data import cleanup_all_test_data


class TestR2StorageIntegration(unittest.TestCase):
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

    def tearDown(self):
        for mem_id in self.created_mem_ids:
            try:
                delete_memory(mem_id)
            except Exception:
                pass
        self.created_mem_ids.clear()

    def test_01_sanitize_filename(self):
        self.assertEqual(sanitize_filename("test document.pdf"), "test_document.pdf")
        self.assertEqual(sanitize_filename("../../../secret/plan.txt"), "plan.txt")
        self.assertEqual(sanitize_filename("special@#&*()chars.png"), "special_chars.png")
        self.assertEqual(sanitize_filename(""), "unnamed_file")

    def test_02_storage_service_key_generation(self):
        storage = StorageService()
        key = storage.generate_storage_key("quantum_research.pdf", prefix="files/test")
        self.assertTrue(key.startswith("files/test/"))
        self.assertTrue(key.endswith("quantum_research.pdf"))
        now = datetime.now(timezone.utc)
        self.assertIn(f"/{now.strftime('%Y')}/{now.strftime('%m')}/", key)

    def test_03_mock_storage_service_operations(self):
        storage = StorageService()
        storage.enabled = True
        mock_s3 = MagicMock()
        storage.s3_client = mock_s3
        storage.bucket_name = "test-r2-bucket"

        # 1. Upload file
        mock_s3.put_object.return_value = {}
        mock_s3.generate_presigned_url.return_value = "https://mock-r2.com/files/test.pdf?token=123"

        res = storage.upload_file(b"dummy pdf bytes", "test.pdf", mime_type="application/pdf", prefix="files/test")
        self.assertIsNotNone(res)
        self.assertEqual(res["filename"], "test.pdf")
        self.assertEqual(res["mime_type"], "application/pdf")
        self.assertEqual(res["size_bytes"], 15)
        self.assertIn("https://mock-r2.com/", res["url"])
        mock_s3.put_object.assert_called_once()

        # 2. Presigned download URL
        url = storage.get_presigned_download_url("files/test/2026/08/test.pdf", filename="test.pdf")
        self.assertEqual(url, "https://mock-r2.com/files/test.pdf?token=123")

        # 3. Presigned upload URL
        mock_s3.generate_presigned_url.return_value = "https://mock-r2.com/put?token=abc"
        upload_meta = storage.get_presigned_upload_url("large_dataset.csv", content_type="text/csv", prefix="files/test")
        self.assertIsNotNone(upload_meta)
        self.assertEqual(upload_meta["upload_url"], "https://mock-r2.com/put?token=abc")

        # 4. Batch delete
        mock_s3.delete_objects.return_value = {"Deleted": [{"Key": "files/test/k1"}, {"Key": "files/test/k2"}]}
        count = storage.delete_files(["files/test/k1", "files/test/k2"])
        self.assertEqual(count, 2)
        mock_s3.delete_objects.assert_called_once()

    def test_04_memory_service_single_chunk_with_attachments(self):
        attachments = [
            {
                "key": "files/test/2026/08/spec1.pdf",
                "filename": "spec1.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 1024,
                "url": "https://example.com/spec1.pdf",
                "created_at": datetime.now(timezone.utc).isoformat()
            }
        ]
        mem = add_memory(
            content="Single chunk memory with architecture PDF attachment.",
            category="test_suite",
            source_agent="test_runner",
            tags=["test_runner", "test_suite"],
            attachments=attachments
        )
        self.created_mem_ids.append(mem["id"])

        self.assertIsNotNone(mem["id"])
        self.assertEqual(mem["chunks_created"], 1)
        self.assertEqual(len(mem["attachments"]), 1)
        self.assertEqual(mem["attachments"][0]["filename"], "spec1.pdf")

        # Verify DB row
        with Session(engine) as session:
            item = session.exec(select(MemoryItem).where(MemoryItem.id == mem["id"])).first()
            self.assertIsNotNone(item)
            self.assertIn("spec1.pdf", item.attachments_json)

    def test_05_memory_service_multi_chunk_denormalization(self):
        long_content = (
            "GigaMind Cloudflare R2 and Neon Architecture Specification: "
            "In this section we discuss the complete decoupling of storage artifacts from the vector search engine. "
            * 8
        )
        attachments = [
            {
                "key": "files/test/2026/08/research_paper.pdf",
                "filename": "research_paper.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 204800,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
        ]

        mem = add_memory(
            content=long_content,
            category="test_suite",
            source_agent="test_runner",
            tags=["test_runner", "test_suite"],
            attachments=attachments
        )
        self.created_mem_ids.append(mem["id"])
        self.assertGreater(mem["chunks_created"], 1)
        parent_id = mem["id"]

        # Check DB to verify child chunks have attachments_json denormalized
        with Session(engine) as session:
            parent = session.exec(select(MemoryItem).where(MemoryItem.id == parent_id)).first()
            self.assertIsNotNone(parent)
            self.assertIn("research_paper.pdf", parent.attachments_json)

            children = session.exec(select(MemoryItem).where(MemoryItem.parent_id == parent_id)).all()
            self.assertGreater(len(children), 1)
            for chk in children:
                self.assertIn("research_paper.pdf", chk.attachments_json)

        # Vector search should retrieve the chunk and include attachments
        search_res = search_memory(query="Cloudflare R2 and Neon Architecture Specification", limit=5, scope="memories")
        self.assertTrue(len(search_res) > 0)
        found = any("research_paper.pdf" in str(r.get("attachments", [])) for r in search_res)
        self.assertTrue(found)

    def test_06_cascading_r2_deletion(self):
        storage = StorageService()
        storage.enabled = True
        mock_s3 = MagicMock()
        storage.s3_client = mock_s3
        storage.bucket_name = "test-r2"
        mock_s3.delete_objects.return_value = {"Deleted": [{"Key": "files/test/2026/08/to_delete.pdf"}]}

        with patch("gigamind.services.memory.storage_service", storage):
            mem = add_memory(
                content="Temporary memory to test deletion cascade",
                category="test_suite",
                source_agent="test_runner",
                tags=["test_runner"],
                attachments=[{"key": "files/test/2026/08/to_delete.pdf", "filename": "to_delete.pdf"}]
            )
            mem_id = mem["id"]

            success = delete_memory(mem_id)
            self.assertTrue(success)
            mock_s3.delete_objects.assert_called_once()

    def test_07_fastapi_rest_endpoints(self):
        payload = {
            "content": "API Test Fact with attached whitepaper",
            "category": "test_suite",
            "source_agent": "test_runner",
            "tags": ["test_runner", "test_suite"],
            "attachments": [
                {
                    "key": "files/test/2026/08/api_doc.pdf",
                    "filename": "api_doc.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": 4096
                }
            ]
        }
        res = self.client.post("/api/v1/add_memory", json=payload, headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        mem_id = data["memory"]["id"]
        self.created_mem_ids.append(mem_id)

        # Search Memory
        search_req = {"query": "API Test Fact whitepaper", "limit": 3, "scope": "memories"}
        search_res = self.client.post("/api/v1/search_memory", json=search_req, headers=self.auth_headers)
        self.assertEqual(search_res.status_code, 200)
        s_data = search_res.json()
        self.assertIn("results", s_data)
        self.assertTrue(len(s_data["results"]) > 0)

        # Update Memory Attachments
        update_payload = {
            "content": "Updated content with additional attachment",
            "category": "test_suite",
            "source_agent": "test_runner",
            "tags": ["test_runner", "test_suite"],
            "attachments": [
                {
                    "key": "files/test/2026/08/api_doc.pdf",
                    "filename": "api_doc.pdf"
                },
                {
                    "key": "files/test/2026/08/extra.png",
                    "filename": "extra.png"
                }
            ]
        }
        up_res = self.client.put(f"/api/v1/memories/{mem_id}", json=update_payload, headers=self.auth_headers)
        self.assertEqual(up_res.status_code, 200)
        up_data = up_res.json()
        self.assertEqual(len(up_data["memory"]["attachments"]), 2)

    def test_08_fastmcp_sse_tools(self):
        req_body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {}
        }
        res = self.client.post("/messages", json=req_body)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        tools = data["result"]["tools"]
        tool_names = [t["name"] for t in tools]

        self.assertIn("search_memory", tool_names)
        self.assertIn("add_memory", tool_names)
        self.assertIn("upload_file_to_storage", tool_names)
        self.assertIn("get_file_download_url", tool_names)
        self.assertIn("get_file_upload_url", tool_names)
        self.assertIn("list_storage_files", tool_names)

        # Test add_memory tool call
        add_call = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "add_memory",
                "arguments": {
                    "content": "FastMCP Tool Memory with attached file keys",
                    "category": "test_suite",
                    "source_agent": "test_runner",
                    "tags": ["test_runner", "test_suite"],
                    "file_keys": ["files/test/2026/08/mcp_spec.pdf"]
                }
            }
        }
        call_res = self.client.post("/messages", json=add_call)
        self.assertEqual(call_res.status_code, 200)
        mcp_res = call_res.json()
        content_text = json.loads(mcp_res["result"]["content"][0]["text"])
        self.assertTrue(content_text["success"])
        created_mem_id = content_text["memory"]["id"]
        self.created_mem_ids.append(created_mem_id)


if __name__ == "__main__":
    unittest.main()
