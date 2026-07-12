"""Run with: python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"""

import uvicorn

from app.config import get_settings

if __name__ == "__main__":
    s = get_settings()
    uvicorn.run("app.main:app", host=s.host, port=s.port, reload=True)
