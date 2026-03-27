# Strategic Opportunity Engine

An AI-powered intelligence system that researches market opportunities, analyzes case studies, and projects ROI impact for businesses. Combines web search, LLM analysis, and user authentication for a complete opportunity evaluation platform.

---

## 🎯 What It Does

1. **Search Phase** – Uses Tavily API to find recent market research and case studies for a given topic
2. **Analysis Phase** – Uses Groq LLM to score relevance, extract metrics, and model ROI projections
3. **Reporting** – Generates markdown reports and stores them per-user in PostgreSQL
4. **Web Interface** – Authenticated Flask app with dashboard, report history, and exports

**Example Workflow:**
```
User enters: "Logistics Efficiency"
    ↓
Search Agent finds: 3 case studies on logistics automation ROI
    ↓
Analyst Agent scores: Only keeps high-quality data (score > 7)
    ↓
Report Pipeline generates: Markdown report with ROI projections
    ↓
User sees: Dashboard with downloadable report history
```

---

## 🏗️ Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Web Search** | Tavily API | Market research & case study discovery |
| **LLM** | Groq Cloud | Fast analysis & relevance scoring |
| **Web App** | Flask | User auth & report management |
| **Database** | PostgreSQL (Supabase) | Store users & report history |
| **Runtime** | Python 3.x | Main orchestration |

**Dependencies:**  
See [requirements.txt](requirements.txt) – includes: tavily, groq, flask, psycopg, dotenv, pydantic

---

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- API keys for:
  - [Tavily](https://tavily.com) – web search
  - [Groq](https://console.groq.com) – LLM inference
- PostgreSQL database (use [Supabase free tier](https://supabase.com) for quick setup)
- Optional: OpenAI key (future integrations)

### 1. Clone & Setup Environment

```bash
# Clone repo
git clone https://github.com/yourusername/strategic-opportunity-engine.git
cd strategic-opportunity-engine

# Create Python virtual environment
python -m venv .venv

# Activate virtual environment
# Windows:
.\.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure `.env`

Create a `.env` file in the project root:

```env
# API Keys
TAVILY_API_KEY=your_tavily_api_key_here
GROQ_API_KEY=your_groq_api_key_here
OPENAI_API_KEY=your_openai_key_here  # Optional, for future features

# Database (Get from Supabase > Settings > Database > Connection String)
DATABASE_URL=postgresql://postgres:<PASSWORD>@db.<PROJECT_ID>.supabase.co:5432/postgres?sslmode=require

# Flask
APP_SECRET_KEY=your-secure-random-key-change-in-production
FLASK_ENV=development

# Optional: Mode preferences
DEFAULT_MODE=public_markets
```

**Finding your Supabase connection string:**
1. Go to [supabase.com](https://supabase.com) → Create a new project (free tier)
2. Database → Connection Pooler → URI
3. Copy the full URI and paste into `DATABASE_URL` above

### 3. Initialize Database

```bash
python web_app.py
```

The app will auto-create tables on startup. You should see:
```
 * Running on http://127.0.0.1:5000
```

### 4. Run Search Agent (Test)

To verify search is working standalone:

```bash
python search_agent.py
# Prompts for topic, searches Tavily, prints results
```

### 5. Open Web App

Visit **http://localhost:5000** in your browser:
- Sign up for a new account
- Log in
- Click "New Report"
- Enter a topic (e.g., "Artificial Intelligence in Supply Chain")
- View report results and history

---

## 📁 Project Structure

```
.
├── web_app.py                 # Flask app: auth, routes, DB queries
├── main.py                    # Report formatting & markdown generation
├── search_agent.py            # Phase 1: Tavily web search
├── analyst_agent.py           # Phase 2: Groq LLM analysis & scoring
├── requirements.txt           # Python dependencies
├── .env                       # Config (DO NOT COMMIT - in .gitignore)
├── .gitignore                 # Git ignore rules (includes .env, __pycache__, etc.)
│
├── templates/                 # Flask HTML templates
│   ├── auth.html              # Login / sign-up form
│   ├── dashboard.html         # User report list & overview
│   ├── report.html            # Individual report view
│   └── insights.html          # Report insights & charts
│
├── static/                    # CSS & client-side assets
│   └── app.css                # Styling
│
├── data/                      # Local SQLite (deprecated, using PostgreSQL now)
│   └── app.db
│
└── reports/                   # Markdown reports stored as files
    ├── memo_20260320_143818.md
    └── ...
```

---

## 🔄 Architecture

### Three-Phase Pipeline

```
┌─────────────────────────────────────────┐
│ Phase 1: SearchAgent (search_agent.py)  │
├─────────────────────────────────────────┤
│ Input:  User topic (e.g., "AI in HR")   │
│ Action: Refine query → Call Tavily API  │
│ Output: [{title, url, content}, ...]    │
└────────────────┬────────────────────────┘
                 ↓
        [Raw Search Results]
                 ↓
┌─────────────────────────────────────────┐
│ Phase 2: AnalystAgent (analyst_agent.py)│
├─────────────────────────────────────────┤
│ Input:  Raw search results              │
│ Action: Score relevance, extract metrics│
│ Filter: Keep score > 7 only             │
│ Output: [{score, metrics, roi}, ...]    │
└────────────────┬────────────────────────┘
                 ↓
      [Ranked & Scored Results]
                 ↓
┌─────────────────────────────────────────┐
│ Phase 3: Report Pipeline (main.py)      │
├─────────────────────────────────────────┤
│ Input:  Analyzed results                │
│ Action: Format as markdown              │
│ Output: Markdown report (stored in DB) │
└─────────────────────────────────────────┘
```

---

## 🗄️ Database Schema

When the app starts, these tables are auto-created:

| Table | Purpose |
|-------|---------|
| `users` | User accounts (email, password hash, admin flag) |
| `reports` | Report metadata (user_id, topic, created_at, content) |
| `usage_logs` | Track API calls per user for rate limiting |

---

## 🛠️ Common Tasks

### Add a New API Key
Edit `.env` and restart the app:
```bash
# Update .env
nano .env

# Restart
python web_app.py
```

### Create Admin User
The first user (user_id = 1) is auto-admin. Subsequent users are free tier (2 reports/month limit).

### Export User Data
From the dashboard, click "Export" on any report to download as markdown or CSV.

### Connection Issues?
If you see `psycopg.errors.ConnectionTimeout`:
1. Verify `DATABASE_URL` is correct in `.env`
2. Ensure URL includes `?sslmode=require`
3. Check firewall: `Test-NetConnection db.<project>.supabase.co -Port 5432` (Windows PowerShell)
4. Try Supabase pooler endpoint (port 6543) instead of direct connection (port 5432)

---

## 📋 Development Notes

### Current Implementation Status

✅ **Phase 1 – SearchAgent**: Fully working  
- Uses Tavily API for advanced web search
- Refines queries for ROI-focused results
- Error handling & validation

🔄 **Phase 2 – AnalystAgent**: Implemented  
- Uses Groq LLM for relevance scoring
- Extracts numerical metrics
- Filters low-quality results

✅ **Phase 3 – Reporting**: Fully working  
- Markdown report generation
- Database storage & retrieval
- CSV export support

✅ **Web App**: Fully working  
- User auth (login/signup)
- Report history dashboard
- Per-user usage limits

### Future Enhancements
- [ ] OpenAI integration for alternative LLM
- [ ] Advanced filtering (date range, industry vertical)
- [ ] Chart/graph visualization
- [ ] Email report delivery
- [ ] Team collaboration & shared reports

---

## 🧪 Testing

### Test SearchAgent Alone
```bash
python search_agent.py
# Enter topic → prints raw Tavily results
```

### Test with All Phases
```bash
python main.py
# Enter topic → prints final markdown report
```

### Test Web App Locally
```bash
python web_app.py
# Visit http://localhost:5000
# Create account → generate report → view dashboard
```

---

## 🔒 Security Notes

- **Never commit `.env`** – it's in `.gitignore` by default
- **Rotate secrets regularly** – especially if exposed in git history
  - In Supabase: Database → Generate new password
  - Reset API keys in Tavily / Groq dashboards
- **Use strong `APP_SECRET_KEY` in production** – generate with:
  ```bash
  python -c "import secrets; print(secrets.token_hex(32))"
  ```
- **Enable HTTPS in production** – use a reverse proxy (nginx, Gunicorn)

---

## 📄 License

This project is open-source. See LICENSE file for details.

---

## 💬 Support

- **Issues?** Open a GitHub issue with error traceback
- **Suggestions?** Create a discussion or PR
- **API Questions?** Check:
  - [Tavily Docs](https://tavily.com/docs)
  - [Groq Docs](https://console.groq.com/docs)
  - [Supabase Docs](https://supabase.com/docs)
- **Flask Help?** See [Flask Documentation](https://flask.palletsprojects.com/)

---

**Happy researching! 🚀**
