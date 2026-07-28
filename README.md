# 🧠 GigaMind: Personal Memory Engine for AI

<img width="105" height="105" alt="artworks-000623298505-jfad qoikf-t1080x1080" src="https://github.com/user-attachments/assets/a5875dd1-418d-4af5-b304-98d67af2e65d" />


---

## ✨ Features

- **Universal Multi-Protocol Engine**:
  - **FastMCP SSE & Stdio** (`/sse`, `/messages`) for Claude Desktop, Cursor, and Windsurf.
  - **OAuth 2.0 Authorization Server** (`/oauth/authorize`, `/oauth/token`) for Claude Web (`claude.ai`) Custom Connectors.
  - **REST API + OpenAPI 3.1.0** (`/openapi.json`, `/api/v1/*`) for ChatGPT Custom GPT Actions & Gemini.
- **Hybrid Search Engine**: Vector similarity embeddings (via `sentence-transformers/all-MiniLM-L6-v2`) + keyword search over SQLite / SQLModel.
- **1-Click Bulk Chat Importer**: Python CLI to parse historical chat exports from ChatGPT, Claude, and Gemini into memory.
- **Zero Provider Storage Guarantee**: Transient headers and dynamic tool execution prevent AI vendors from storing personal context.

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
4. Render automatically reads `render.yaml` or set:
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn gigamind.main:app --host 0.0.0.0 --port $PORT`
5. Add Environment Variable: `GIGAMIND_API_KEY=your-secure-password`.

Render will host GigaMind 24/7 with free SSL: `https://gigamind.onrender.com`.

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
   - **URL**: `https://gigamind.onrender.com/sse`
   - **Authorize URL**: `https://gigamind.onrender.com/oauth/authorize`
3. Click **Add**. When prompted, enter your GigaMind Master Password on the authorization page!

---

### 2. ChatGPT (Custom GPT Actions)
1. Create a Custom GPT -> **Actions** -> **Import from URL**.
2. Paste: `https://gigamind.onrender.com/openapi.json`.
3. Set Authentication to **API Key** -> **Bearer** and paste `GIGAMIND_API_KEY`.

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
        "URL": "https://gigamind.onrender.com/sse",
        "API_KEY": "your-secure-password"
      }
    }
  }
}
```

---

## 📄 License
MIT License.
