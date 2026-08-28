import os
import json
import base64
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

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


class TestR2StorageIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)
        cls.auth_headers = {"Authorization": f"Bearer {API_KEY}"}

    def test_01_sanitize_filename(self):
        self.assertEqual(sanitize_filename("test document.pdf"), "test_document.pdf")
        self.assertEqual(sanitize_filename("../../../secret/plan.txt"), "plan.txt")
        self.assertEqual(sanitize_filename("special@#&*()chars.png"), "special_chars.png")
        self.assertEqual(sanitize_filename(""), "unnamed_file")
    def test_02_storage_service_key_generation(self):
        storage = StorageService()
        key = storage.generate_storage_key("quantum_research.pdf", prefix="research")
        self.assertTrue(key.startswith("research/"))
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

        res = storage.upload_file(b"dummy pdf bytes", "test.pdf", mime_type="application/pdf")
        self.assertIsNotNone(res)
        self.assertEqual(res["filename"], "test.pdf")
        self.assertEqual(res["mime_type"], "application/pdf")
        self.assertEqual(res["size_bytes"], 15)
        self.assertIn("https://mock-r2.com/", res["url"])
        mock_s3.put_object.assert_called_once()

        # 2. Presigned download URL
        url = storage.get_presigned_download_url("files/2026/08/test.pdf", filename="test.pdf")
        self.assertEqual(url, "https://mock-r2.com/files/test.pdf?token=123")

        # 3. Presigned upload URL
        mock_s3.generate_presigned_url.return_value = "https://mock-r2.com/put?token=abc"
        upload_meta = storage.get_presigned_upload_url("large_dataset.csv", content_type="text/csv")
        self.assertIsNotNone(upload_meta)
        self.assertEqual(upload_meta["upload_url"], "https://mock-r2.com/put?token=abc")

        # 4. Batch delete
        mock_s3.delete_objects.return_value = {"Deleted": [{"Key": "k1"}, {"Key": "k2"}]}
        count = storage.delete_files(["k1", "k2"])
        self.assertEqual(count, 2)
        mock_s3.delete_objects.assert_called_once()

    def test_04_memory_service_single_chunk_with_attachments(self):
        attachments = [
            {
                "key": "files/2026/08/spec1.pdf",
                "filename": "spec1.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 1024,
                "url": "https://example.com/spec1.pdf",
                "created_at": datetime.now(timezone.utc).isoformat()
            }
        ]
        mem = add_memory(
            content="Single chunk memory with architecture PDF attachment.",
            category="architecture",
            source_agent="claude",
            tags=["r2", "storage"],
            attachments=attachments
        )

        self.assertIsNotNone(mem["id"])
        self.assertEqual(mem["chunks_created"], 1)
        self.assertEqual(len(mem["attachments"]), 1)
        self.assertEqual(mem["attachments"][0]["filename"], "spec1.pdf")

        # Verify DB row
        with Session(engine) as session:
            item = session.exec(select(MemoryItem).where(MemoryItem.id == mem["id"])).first()
            self.assertIsNotNone(item)
            self.assertIn("spec1.pdf", item.attachments_json)

        # Clean up
        delete_memory(mem["id"])

    def test_05_memory_service_multi_chunk_denormalization(self):
        # Long content (>600 characters) to trigger chunking
        long_content = (
            "GigaMind Cloudflare R2 and Neon Architecture Specification: "
            "In this section we discuss the complete decoupling of storage artifacts from the vector search engine. "
            * 8
        )
        self.assertGreater(len(long_content), 600)

        attachments = [
            {
                "key": "files/2026/08/research_paper.pdf",
                "filename": "research_paper.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 204800,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
        ]

        mem = add_memory(
            content=long_content,
            category="research",
            source_agent="gpt",
            tags=["multi-chunk", "r2"],
            attachments=attachments
        )

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
                self.assertIn("research_paper.pdf", chk.attachments_json, "Child chunk must retain denormalized attachments_json")

        # Vector search should retrieve the chunk and include attachments
        search_res = search_memory(query="Cloudflare R2 and Neon Architecture Specification", limit=5)
        self.assertTrue(len(search_res) > 0)
        found = any("research_paper.pdf" in str(r.get("attachments", [])) for r in search_res)
        self.assertTrue(found, "search_memory candidate should contain hydrated attachments")

        # Clean up
        delete_memory(parent_id)

    def test_06_cascading_r2_deletion(self):
        storage = StorageService()
        storage.enabled = True
        mock_s3 = MagicMock()
        storage.s3_client = mock_s3
        storage.bucket_name = "test-r2"
        mock_s3.delete_objects.return_value = {"Deleted": [{"Key": "files/2026/08/to_delete.pdf"}]}

        with patch("gigamind.services.memory.storage_service", storage):
            mem = add_memory(
                content="Temporary memory to test deletion cascade",
                category="test",
                attachments=[{"key": "files/2026/08/to_delete.pdf", "filename": "to_delete.pdf"}]
            )
            mem_id = mem["id"]

            success = delete_memory(mem_id)
            self.assertTrue(success)

            # Ensure R2 delete_objects was called
            mock_s3.delete_objects.assert_called_once()

    def test_07_fastapi_rest_endpoints(self):
        # 1. Add Memory with Attachments
        payload = {
            "content": "API Test Fact with attached whitepaper",
            "category": "api_test",
            "source_agent": "cursor",
            "tags": ["api", "integration"],
            "attachments": [
                {
                    "key": "files/2026/08/api_doc.pdf",
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

        # 2. Search Memory
        search_req = {"query": "API Test Fact whitepaper", "limit": 3}
        search_res = self.client.post("/api/v1/search_memory", json=search_req, headers=self.auth_headers)
        self.assertEqual(search_res.status_code, 200)
        s_data = search_res.json()
        self.assertIn("results", s_data)
        self.assertTrue(len(s_data["results"]) > 0)

        # 3. Update Memory Attachments
        update_payload = {
            "content": "Updated content with additional attachment",
            "attachments": [
                {
                    "key": "files/2026/08/api_doc.pdf",
                    "filename": "api_doc.pdf"
                },
                {
                    "key": "files/2026/08/extra.png",
                    "filename": "extra.png"
                }
            ]
        }
        up_res = self.client.put(f"/api/v1/memories/{mem_id}", json=update_payload, headers=self.auth_headers)
        self.assertEqual(up_res.status_code, 200)
        up_data = up_res.json()
        self.assertEqual(len(up_data["memory"]["attachments"]), 2)

        # 4. Delete Memory
        del_res = self.client.delete(f"/api/v1/memories/{mem_id}", headers=self.auth_headers)
        self.assertEqual(del_res.status_code, 200)

    def test_08_fastmcp_sse_tools(self):
        # Test tools/list via JSON-RPC endpoint
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
                    "category": "mcp_test",
                    "source_agent": "claude",
                    "tags": ["mcp"],
                    "file_keys": ["files/2026/08/mcp_spec.pdf"]
                }
            }
        }
        call_res = self.client.post("/messages", json=add_call)
        self.assertEqual(call_res.status_code, 200)
        mcp_res = call_res.json()
        content_text = json.loads(mcp_res["result"]["content"][0]["text"])
        self.assertTrue(content_text["success"])
        created_mem_id = content_text["memory"]["id"]

        # Clean up
        delete_memory(created_mem_id)


if __name__ == "__main__":
    unittest.main()
