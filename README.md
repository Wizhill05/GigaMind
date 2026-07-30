# 🧠 GigaMind: Universal Personal Memory Engine for AI

GigaMind is an open-source, production-grade **Personal Memory Engine & 2-Stage RAG Pipeline** designed for AI models and coding harnesses. It acts as a single source of truth for your long-term preferences, identity rules, code snippets, and conversation logs.

---

## ✨ Core Features

- **⚡ 2-Stage RAG Retrieval Engine**:
  - **Stage 1 (Vector Candidate Selection)**: Native PostgreSQL `pgvector` HNSW index similarity search ($O(\log N)$ cosine distance matching) or vectorized local scanning.
  - **Stage 2 (Cross-Encoder Reranker)**: Re-ranks candidate matches via Voyage/Cohere API rerankers or GigaMind's zero-dependency token-interaction cross-scorer (BM25 TF-IDF + phrase overlap + term density).
- **✂️ Smart Text Chunking**: Hierarchical recursive text splitting (500-character windows with 100-character overlaps) for long memories, documents, and dialogue exports.
- **🎛️ Tactical Dashboard UI (`/dashboard`)**: Modern Render-style dark theme React SPA (Vite + TypeScript + Tailwind CSS) with 8-bit pixel icons, 60fps micro-animations, spotlight search (`⌘K`), toast notifications, and interactive analytics charts.
- **🏷️ Origin Source Agent Tracking**: Tracks exactly which AI model or user created each memory (`claude`, `gpt`, `gemini`, `user`, `system`, etc.).
- **🌐 Universal Multi-Protocol Support**:
  - **FastMCP SSE & Stdio** (`/sse`, `/messages`) for Claude Desktop, Claude Code, Cursor, Windsurf, and OpenCode.
  - **OAuth 2.0 Authorization Server** (`/oauth/authorize`, `/oauth/token`) for `claude.ai` Custom Connectors.
  - **REST API + OpenAPI 3.1.0** (`/openapi.json`, `/api/v1/*`) for ChatGPT Custom GPT Actions & Gemini.
- **🗑️ Cascading Parent-Child Cleanup**: Deleting a parent document automatically wipes all associated vector chunks atomically.

---

## 🛠️ Self-Hosting Guide

### Step 1: Database Setup (Supabase PostgreSQL + `pgvector`)

1. Create a free account and project at **[Supabase.com](https://supabase.com)**.
2. In the Supabase dashboard, open the **SQL Editor** and run:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
3. Go to **Project Settings** $\rightarrow$ **Database** $\rightarrow$ **Connection String**.
4. Copy the **URI / Connection String** (Session or Transaction pooler, e.g.):
   `postgresql://postgres.[REF]:[YOUR-PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres`

---

### Step 2: Host on Render.com (24/7 Free Hosting)

1. Fork or clone this repository to your GitHub account.
2. Sign up or log into **[Render.com](https://render.com)**.
3. Click **New +** $\rightarrow$ **Web Service** and connect your GigaMind repository.
4. Set the build and start commands:
   - **Environment**: `Python`
   - **Build Command**: `(cd frontend && npm install && npm run build) || true; pip install -r requirements.txt`
   - **Start Command**: `uvicorn gigamind.main:app --host 0.0.0.0 --port $PORT`
5. Configure Environment Variables under **Environment**:
   | Variable | Value / Description |
   |---|---|
   | `GIGAMIND_API_KEY` | `your-secure-master-password` |
   | `DATABASE_URL` | Your Supabase PostgreSQL connection string from Step 1 |
   | `GEMINI_API_KEY` | *(Optional)* Google AI Studio API key for Gemini embeddings |
   | `VOYAGE_API_KEY` | *(Optional)* Voyage AI API key for cross-encoder reranking |
   | `COHERE_API_KEY` | *(Optional)* Cohere API key for cross-encoder reranking |
6. Click **Create Web Service**. Render will deploy GigaMind at `https://your-app-name.onrender.com`.

---

### Step 3: Local Host Alternative (SQLite Engine)

If you prefer running GigaMind locally without cloud dependencies:

1. Clone the repository and install Python dependencies:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. Build the React frontend SPA:
   ```bash
   cd frontend && npm install && npm run build && cd ..
   ```
3. Create a `.env` file:
   ```env
   PORT=8000
   GIGAMIND_API_KEY=gigamind-secret-key-change-me
   DB_PATH=./gigamind.db
   ```
4. Start the FastAPI + FastMCP server:
   ```bash
   uvicorn gigamind.main:app --reload --port 8000
   ```
5. Access local endpoints:
   - **Tactical Dashboard**: `http://localhost:8000/dashboard`
   - **Healthcheck**: `http://localhost:8000/`
   - **OpenAPI Spec**: `http://localhost:8000/openapi.json`
   - **FastMCP SSE Endpoint**: `http://localhost:8000/sse`

---

## 🔗 Connecting GigaMind to AI Services & Coding Harnesses

### 1. Claude Web (`claude.ai`) Custom Connector (OAuth 2.0)

1. Navigate to **`claude.ai`** $\rightarrow$ **Account Settings** $\rightarrow$ **Integrations / Connectors**.
2. Click **Add Custom Connector**:
   - **Name**: `GigaMind`
   - **URL**: `https://your-app-name.onrender.com/sse`
   - **Authorize URL**: `https://your-app-name.onrender.com/oauth/authorize`
3. Click **Save**. When prompted by `claude.ai`, enter your `GIGAMIND_API_KEY` on the GigaMind OAuth login screen.

---

### 2. Claude Code (CLI Harness)

To give **Claude Code** full read/write access to your GigaMind memory engine:

Add GigaMind to your Claude Code MCP configuration (`~/.claude.json` or `.claude/config.json`):

```json
{
  "mcpServers": {
    "gigamind": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-sse"],
      "env": {
        "URL": "https://your-app-name.onrender.com/sse",
        "API_KEY": "your-secure-master-password"
      }
    }
  }
}
```

Or connect via CLI command:
```bash
claude mcp add gigamind https://your-app-name.onrender.com/sse --header "Authorization: Bearer your-secure-master-password"
```

---

### 3. Claude Desktop, OpenCode, Cursor & Windsurf (FastMCP SSE)

Add GigaMind to your workspace MCP configuration file (`claude_desktop_config.json` or `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "gigamind": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-sse"],
      "env": {
        "URL": "https://your-app-name.onrender.com/sse",
        "API_KEY": "your-secure-master-password"
      }
    }
  }
}
```

---

### 4. ChatGPT (Custom GPT Actions & REST API)

1. Open **ChatGPT** $\rightarrow$ **Explore GPTs** $\rightarrow$ **Create**.
2. Go to **Configure** $\rightarrow$ **Actions** $\rightarrow$ **Import from URL**.
3. Enter your OpenAPI endpoint:
   `https://your-app-name.onrender.com/openapi.json`
4. Set **Authentication** to **API Key** $\rightarrow$ **Auth Type: Bearer** and paste your `GIGAMIND_API_KEY`.
5. Copy instructions from **[`SKILL.md`](./SKILL.md)** into the GPT **Instructions** text box!

---

### 5. GigaMind Skill & System Directive (`SKILL.md`)

GigaMind includes an agent directive file in **[`SKILL.md`](./SKILL.md)**. 

To enable automatic memory search, rule fetching, and memory insertion across your prompts, copy the content of [`SKILL.md`](./SKILL.md) into:
- **Claude**: Project System Instructions or `.claude/skills/`
- **ChatGPT**: Custom GPT Instructions
- **Cursor / OpenCode**: `.cursorrules` or system prompt configuration

---

## 🧪 Edge-Case Verification & Reliability Testing

GigaMind comes with an edge-case test suite (`tests/test_deployed_rag_edgecases.sh`) that evaluates **23 critical edge cases**:
- Authentication Security (missing, invalid, and valid Bearer tokens)
- Smart Text Chunking (<600 chars single chunk vs >600 chars multi-chunk windowing)
- Multi-byte Unicode & Code Blocks (emojis 🧠🤖, quotes, backslashes, CJK text)
- Boundary Character Thresholds (599 vs 601 characters)
- 2-Stage Retrieval & Cross-Encoder Reranking score calculations
- Category & Source Agent Filtering isolation
- Cascading Parent-Child Relational Deletions

### Running the Test Suite

Once GigaMind is hosted, verify your server deployment:

```bash
# Run test suite against your deployed Render engine
DEPLOYED_URL="https://your-app-name.onrender.com" GIGAMIND_API_KEY="your-secure-master-password" ./tests/test_deployed_rag_edgecases.sh
```

Or run locally:
```bash
python3 tests/run_tests.py
```

Expected Output:
```
=====================================================
                 EXECUTION SUMMARY                  
=====================================================
Total Tests Executed : 23
Passed               : 23
Failed               : 0
ALL EDGE-CASE TESTS PASSED SUCCESSFULLY!
```

---

## 📥 Ingesting Past Chat History

Import conversation exports from ChatGPT, Claude, or Gemini into GigaMind:

```bash
python3 -m gigamind.cli.importer --chatgpt ./chatgpt_history.json --claude ./claude_history.json
```

---

## 📄 License

MIT License. Free to use, modify, and self-host.
