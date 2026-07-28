# 🧠 GigaMind: Personal Memory Engine for AI

<img width="1440" height="360" alt="GigaMind Header Banner" src="https://github.com/user-attachments/assets/e84bb1b9-4026-433c-a98e-94cf769d443c" />

---

## ✨ Features

- **🎛️ Tactical Dashboard UI (`/dashboard`)**: High-end Industrial Brutalist control panel (`rounded-none`, sharp 1px grid borders, dark substrate) with **live natural language vector search**, real-time relevance percentage indicators (`[MATCH: 94.2%]`), and **full CRUD memory management** (edit, delete, search, create profile rules).
- **Universal Multi-Protocol Engine**:
  - **FastMCP SSE & Stdio** (`/sse`, `/messages`) for Claude Desktop, Cursor, and Windsurf.
  - **OAuth 2.0 Authorization Server** (`/oauth/authorize`, `/oauth/token`) for Claude Web (`claude.ai`) Custom Connectors.
  - **REST API + OpenAPI 3.1.0** (`/openapi.json`, `/api/v1/*`) for ChatGPT Custom GPT Actions & Gemini.
- **Multimodal Embedding Suite**: Built-in support for **Google Gemini `models/gemini-embedding-2`** (text, code, images, PDFs), Voyage AI (`voyage-3-lite`), HuggingFace Cloud (`BAAI/bge-small-en-v1.5`), and zero-memory local feature vectors.
- **Supabase `pgvector` & SQLite Integration**: Seamless 24/7 permanent cloud database persistence.
- **1-Click Bulk Chat Importer**: Python CLI to parse historical chat exports from ChatGPT, Claude, and Gemini into memory.

---

## 🖥️ Dashboard Control Panel (`/dashboard`)

Visit `https://gigamind-md53.onrender.com/dashboard` (or `http://localhost:8000/dashboard` locally):

```
┌───────────────────────────────────────────────────────────────────────────┐
│ GIGAMIND // TELEMETRY & CONTROL                       [ API KEY: ***** ]  │
├───────────────────────────────────────────────────────────────────────────┤
│ [ MEMORIES: 128 ]  [ RULES: 14 ]  [ CHAT LOGS: 35 ]  [ SESSIONS: 8 ]       │
├───────────────────────────────────────────────────────────────────────────┤
│ [ LIVE VECTOR SEARCH ]                                                    │
│ > preferred programming language and framework...            [ SEARCH ]   │
│                                                                           │
│   >>> RESULT: [PROFILE] preferred_language = Python / FastAPI [MATCH 96.4%]│
│   >>> RESULT: [MEMORY] User prefers Hono & FastMCP            [MATCH 88.1%]│
├───────────────────────────────────────────────────────────────────────────┤
│ MEMORY REPOSITORY                              │ PROFILE RULES            │
│ • [CODING] Aryan prefers Python & FastAPI      │ • USER_NAME = Aryan      │
│   [EDIT]  [DELETE]                             │ • CODE_STYLE = Strict    │
└────────────────────────────────────────────────┴──────────────────────────┘
```

---

## 🛠️ Quick Start (Local Development)

### 1. Install Dependencies
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Environment (`.env`)
```bash
cp .env.example .env
```
Edit `.env`:
```env
PORT=8000
GIGAMIND_API_KEY=your-secure-master-password
DB_PATH=./gigamind.db
```

### 3. Run Server
```bash
uvicorn gigamind.main:app --reload --port 8000
```
Server endpoints:
- **Tactical Dashboard**: `http://localhost:8000/dashboard`
- **Healthcheck**: `http://localhost:8000/`
- **OpenAPI Spec**: `http://localhost:8000/openapi.json`
- **MCP SSE Endpoint**: `http://localhost:8000/sse`
- **OAuth Authorize**: `http://localhost:8000/oauth/authorize`
- **REST Endpoints**: `http://localhost:8000/api/v1/*`

---

## ☁️ Deployment: Render Free Tier (100% Free 24/7 Cloud Host)

GigaMind is pre-configured for **Render Free Web Service**:

1. Push code to GitHub.
2. Sign up at [Render.com](https://render.com) (Free Tier).
3. Click **New Web Service** -> Link your `GigaMind` GitHub repo.
4. Set Environment Variables:
   - `GIGAMIND_API_KEY`: your-custom-master-password
   - `GEMINI_API_KEY`: your-google-ai-studio-key
   - `DATABASE_URL`: your-supabase-postgresql-pooler-url
5. Click **Create Web Service**.

Render will host GigaMind 24/7 with free SSL: `https://gigamind-md53.onrender.com`.

---

## 📄 GigaMind System Directive & Skill Prompt (`SKILL.md`)

To instruct any AI model (ChatGPT, Claude, Cursor, Windsurf) **when and how to automatically query or save to GigaMind**, see **[`SKILL.md`](./SKILL.md)**.

Paste the system directive from [`SKILL.md`](./SKILL.md) into:
- **ChatGPT**: Custom GPT **Instructions** box.
- **Cursor**: `.cursorrules` file in your workspace root.
- **Windsurf**: `.windsurfrules` file in your workspace root.
- **Claude**: Project System Instructions in `claude.ai`.

---

## 📥 Ingest Existing Chat History

GigaMind includes a bulk importer CLI for parsing past chat exports:

```bash
python -m gigamind.cli.importer --chatgpt ./conversations.json --claude ./claude_conversations.json
```

---

## 🔗 Connecting GigaMind to AI Services

### 1. Claude Web (`claude.ai`) Custom Connector (OAuth 2.0)
1. Go to `claude.ai` -> **Account Settings** -> **Integrations / Connectors**.
2. Click **Add Custom Connector**:
   - **Name**: `GigaMind`
   - **URL**: `https://gigamind-md53.onrender.com/sse`
   - **Authorize URL**: `https://gigamind-md53.onrender.com/oauth/authorize`
3. Click **Add**. When prompted, enter your GigaMind Master Password on the authorization page!

---

### 2. ChatGPT (Custom GPT Actions & MCP Plugin)
1. Create a Custom GPT -> **Actions** -> **Import from URL**.
2. Paste: `https://gigamind-md53.onrender.com/openapi.json`.
3. Set Authentication to **API Key** -> **Bearer** and paste `GIGAMIND_API_KEY`.
4. Copy instructions from **[`SKILL.md`](./SKILL.md)** into the GPT Instructions!

---

### 3. Claude Desktop & Cursor (FastMCP over SSE)
Add to your `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "gigamind": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-sse"],
      "env": {
        "URL": "https://gigamind-md53.onrender.com/sse",
        "API_KEY": "your-secure-password"
      }
    }
  }
}
```

---

## 📄 License
MIT License.
