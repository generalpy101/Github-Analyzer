# GitHub Review

A local desktop app that generates in-depth reviews of GitHub profiles. Fetches public data via the `gh` CLI, sends it to an LLM for analysis (or uses algorithmic scoring as a fallback), and produces beautiful multi-page HTML reports.

Built with **Flask** (backend), **Tauri** (desktop shell), and **SQLite** (history).

---

## Features

### AI-Powered Profile Review
Enter any GitHub username or profile URL and get a comprehensive assessment covering:
- **Overall score** (0-100) with category breakdowns
- **Profile completeness** (bio, avatar, README, social links)
- **Per-repository reviews** with individual scores, verdicts, and recommendations
- **Code quality observations** referencing actual patterns and languages
- **Activity analysis** with contribution patterns and recent focus
- **Actionable recommendations** prioritized by impact

### Repository Deep-Dive
Click any repo in the report to see a dedicated page with:
- Language breakdown bar chart
- Infrastructure analysis (tests, CI/CD, Docker, docs)
- Pull request statistics and merge rates
- Recent commit history table
- Detailed strengths, improvements, and verdict

### Contribution Graph
GitHub-style heatmap visualization of the past year's contributions, rendered directly in the overview report.

### Deeper Code Analysis
For each top repository, the app fetches:
- **File tree** to detect tests, CI/CD pipelines, Docker configs, and documentation
- **PR stats** including merge rate and code review usage
- **Issue stats** with open/closed ratios

### Extended Thinking
Toggle in Settings to let the LLM reason longer before responding. Produces more detailed and nuanced reviews at the cost of time and tokens. Works with Anthropic, OpenAI, and Ollama.

### Batched Processing
Profiles with many repositories are automatically split into batches of 5 and sent to the LLM in parallel requests, then merged. This keeps response quality high even for accounts with 50+ repos.

### Algorithmic Fallback
When the LLM is unavailable or not configured, the app computes scores algorithmically from repo metadata. A clear banner in the report explains why AI analysis wasn't used, with a collapsible dropdown showing the technical error.

### Multi-Provider LLM Support
- **Anthropic** (Claude Sonnet, Haiku, etc.)
- **OpenAI** (GPT-4o, GPT-4 Turbo, etc.)
- **Ollama** (local models like Llama, Mistral, Qwen)

### Additional
- **PDF export** via the browser print dialog (optimized print stylesheet)
- **Dark mode** with system detection and manual toggle
- **Review history** with search, filterable by username
- **Cache management** — reuse fetched GitHub data or fetch fresh
- **Real-time progress** via Server-Sent Events during generation
- **Cancel/stop** any running or stale generation

---

## Prerequisites

- **Python 3.9+**
- **Node.js 18+** and **npm** (for Tauri)
- **Rust toolchain** (for Tauri desktop build)
- **[GitHub CLI (`gh`)](https://cli.github.com/)** installed and authenticated:
  ```bash
  gh auth login
  ```
- An API key from **Anthropic**, **OpenAI**, or a running **Ollama** instance (optional — algorithmic fallback works without one)

---

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/your-username/github-review.git
cd github-review

# Python dependencies
pip install -r requirements.txt

# Node dependencies (for Tauri)
npm install
```

### 2. Run as a web app (no Tauri)

```bash
python3 app.py
```

Open [http://localhost:5959](http://localhost:5959) in your browser.

### 3. Run as a desktop app (Tauri)

```bash
npm run dev
```

This starts Flask in the background and opens a native Tauri window.

### 4. Configure your LLM

Navigate to **Settings** in the app and:
1. Pick a provider (Anthropic, OpenAI, or Ollama)
2. Enter your API key (not needed for Ollama)
3. Choose a model
4. Click **Test Connection** to verify
5. Optionally enable **Extended Thinking** for deeper analysis

---

## Project Structure

```
github-review/
├── app.py                      # Flask entry point
├── server/                     # Python backend package
│   ├── config.py               #   Config management
│   ├── db.py                   #   SQLite database layer
│   ├── llm_client.py           #   LLM integration (Anthropic/OpenAI/Ollama)
│   ├── fetch_github_data.py    #   GitHub data fetcher via gh CLI
│   ├── generate_report.py      #   HTML report renderer
│   ├── generation_manager.py   #   Background pipeline orchestrator
│   └── fallback_review.py      #   Algorithmic scoring fallback
├── templates/                  # HTML templates
│   ├── app_base.html           #   App shell (nav, theme toggle)
│   ├── app_home.html           #   Home page (generate + history)
│   ├── app_settings.html       #   Settings page
│   ├── app_404.html            #   404 / pending states
│   ├── app_500.html            #   500 error page
│   ├── base.html               #   Report layout (nav, PDF, theme)
│   ├── overview.html           #   Report overview dashboard
│   ├── repos.html              #   Repository list with filters
│   └── repo_detail.html        #   Single repo deep-dive
├── prompt_template.md          # LLM prompt with JSON schema
├── scripts/
│   └── build_sidecar.sh        # PyInstaller build for Tauri sidecar
├── src-tauri/                  # Tauri desktop wrapper (Rust)
├── runtime/                    # Git-ignored runtime data
│   ├── config/config.json      #   App configuration
│   ├── db/github_review.db     #   SQLite database
│   ├── data/<username>/        #   Fetched GitHub data per user
│   └── output/<username>/      #   Generated HTML reports
├── requirements.txt            # Python dependencies
├── requirements-dev.txt        # Dev/build dependencies
├── package.json                # npm scripts for Tauri
└── .gitignore
```

---

## Configuration

Settings are stored in `runtime/config/config.json` and editable through the Settings page.

| Field | Default | Description |
|---|---|---|
| `provider` | `anthropic` | LLM provider: `anthropic`, `openai`, or `ollama` |
| `model` | `claude-sonnet-4-20250514` | Model identifier |
| `api_key` | (empty) | API key for Anthropic or OpenAI |
| `ollama_url` | `http://localhost:11434` | Ollama server URL |
| `top_repos` | `15` | Number of repos to fetch detailed data for (5-30) |
| `extended_thinking` | `false` | Enable extended reasoning for deeper analysis |

---

## Building for Production

### Build the desktop app

```bash
# Build the Python sidecar binary
npm run build:sidecar

# Build the full Tauri app (includes sidecar)
npm run build
```

The output is a native `.dmg` (macOS), `.msi` (Windows), or `.AppImage` (Linux) in `src-tauri/target/release/bundle/`.

### How it works

1. `build_sidecar.sh` uses PyInstaller to compile `app.py` + `server/` + `templates/` into a single binary
2. The binary is placed in `src-tauri/binaries/` with the platform target triple in its name
3. `tauri build` bundles the sidecar binary into the native app
4. At runtime, Tauri starts the sidecar, waits for Flask to be ready on port 5959, and loads the webview

---

## API Endpoints

All endpoints are served by the Flask backend on `http://localhost:5959`.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Home page |
| `GET` | `/settings` | Settings page |
| `GET` | `/report/<run_id>/` | Report overview |
| `GET` | `/report/<run_id>/repos.html` | Report repos page |
| `GET` | `/report/<run_id>/repo/<name>` | Repo deep-dive page |
| `POST` | `/api/generate/<username>` | Start a new review |
| `GET` | `/api/generation-progress/<run_id>` | SSE progress stream |
| `GET` | `/api/active-generation` | Check if a generation is running |
| `POST` | `/api/cancel-generation/<run_id>` | Cancel a running review |
| `POST` | `/api/stop-run/<run_id>` | Stop/cancel any run |
| `POST` | `/api/delete-run/<run_id>` | Delete a run from history |
| `GET` | `/api/history` | List past reviews |
| `GET/POST` | `/api/settings` | Read/write configuration |
| `POST` | `/api/test-connection` | Test LLM connection |
| `GET` | `/api/ai-status` | Check if AI is configured and reachable |
| `GET` | `/api/check-cache/<username>` | Check for cached GitHub data |

---

## How It Works

```
                                     ┌─────────────────┐
   Username ──► Fetch GitHub Data ──►│  github_data.json │
                  (gh CLI)           └────────┬────────┘
                                              │
                         ┌────────────────────┼────────────────────┐
                         │                    │                    │
                    Batch 1/N            Batch 2/N           Batch N/N
                         │                    │                    │
                         ▼                    ▼                    ▼
                    ┌─────────┐          ┌─────────┐         ┌─────────┐
                    │   LLM   │          │   LLM   │         │   LLM   │
                    └────┬────┘          └────┬────┘         └────┬────┘
                         │                    │                    │
                         └────────────────────┼────────────────────┘
                                              │
                                        Merge Reviews
                                              │
                                              ▼
                                   ┌──────────────────┐
                                   │   review.json     │
                                   │   (stored in DB)  │
                                   └────────┬─────────┘
                                            │
                              ┌─────────────┼─────────────┐
                              ▼             ▼             ▼
                         Overview       Repos List    Repo Detail
                          Page            Page          Pages
```

If the LLM is unavailable, the pipeline falls back to algorithmic scoring computed from repo metadata (stars, languages, README presence, commit history, infrastructure signals).

---

## License

This project is for personal use. No license has been specified yet.
