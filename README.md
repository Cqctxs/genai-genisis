# Benchy - AI Performance Optimizer

A production-ready developer tool that analyzes, benchmarks, and optimizes your code using AI. Connect a GitHub repository and get a comprehensive performance report with a CodeMark score.

## Architecture

- **Frontend**: Next.js 14 (App Router), Tailwind CSS, shadcn/ui, React Flow, Recharts, Monaco Editor
- **Backend**: Python FastAPI, LangGraph agent orchestration, PydanticAI structured output
- **AI**: Google Gemini 2.5 Pro for code analysis and optimization
- **Code Parsing**: Tree-sitter for deterministic AST extraction
- **Execution**: Modal cloud containers for safe, isolated benchmark execution
- **Auth**: GitHub OAuth via NextAuth.js

## Quick Start

### Prerequisites

- Node.js 20+
- Python 3.12+
- GitHub OAuth app ([create one](https://github.com/settings/developers))
- Google AI API key ([get one](https://aistudio.google.com/apikey))
- Modal account ([sign up](https://modal.com) and run `modal token new`)

### Setup

1. Clone the repo:
```bash
git clone https://github.com/your-org/genai-genisis.git
cd genai-genisis
```

2. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your API keys

cp frontend/.env.local.example frontend/.env.local
# Edit frontend/.env.local with your GitHub OAuth credentials
```

3. Start the backend:
```bash
cd backend
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
uvicorn main:app --reload
```

4. Start the frontend:
```bash
cd frontend
npm install
npm run dev
```

5. Open http://localhost:3000

### Docker

```bash
docker-compose up
```

## How It Works

1. **Connect** - Sign in with GitHub and paste a repository URL
2. **Analyze** - Tree-sitter parses the AST, Gemini identifies bottlenecks
3. **Benchmark** - Profiling scripts run in Modal containers (pyinstrument / clinic.js)
4. **Visualize** - React Flow graph shows call relationships with performance heatmap
5. **Optimize** - Gemini rewrites bottleneck code with targeted improvements
6. **Score** - Before/after benchmarks produce a composite CodeMark score
