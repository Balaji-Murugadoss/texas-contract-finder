"""All settings in one place. Values come from the .env file, never hard-coded."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
SAM_API_KEY = os.getenv("SAM_API_KEY", "")
MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")

DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.getenv("DB_PATH", DATA_DIR / "contracts.duckdb"))
APP_DB_PATH = Path(os.getenv("APP_DB_PATH", DATA_DIR / "app.sqlite"))
DOCS_DIR = DATA_DIR / "docs"
LOG_PATH = BASE_DIR / "logs" / "agent.jsonl"

SAM_DAILY_BUDGET = int(os.getenv("SAM_DAILY_BUDGET", "8"))
CACHE_HOURS = int(os.getenv("CACHE_HOURS", "12"))
TOP_K_CHUNKS = int(os.getenv("TOP_K_CHUNKS", "5"))
MAX_AGENT_STEPS = int(os.getenv("MAX_AGENT_STEPS", "6"))
USER_AGENT = os.getenv("USER_AGENT", "contract-finder-learning-project (you@example.com)")
