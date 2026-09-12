from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from analysis_fixture import AnalysisFixture
import webapp

fixture = AnalysisFixture()
fixture.__enter__()
app = FastAPI()
app.mount("/app", StaticFiles(directory=webapp._FIGMA_DIST, html=True))
app.add_api_route("/api/app/benchmark", webapp.api_app_benchmark)
app.add_api_route("/api/app/dashboard", webapp.api_app_dashboard)
app.add_api_route("/api/app/tickers", webapp.api_app_tickers)


@app.get("/api/app/me")
def me():
    return {"ok": True, "user": "analysis-test"}


@app.get("/api/app/datasources")
def datasources():
    return {"tossConnected": False, "txCount": 6, "divCount": 2, "tickerCount": 2,
            "brokers": [], "sources": [], "nameMapping": {"mapped": 2, "unmapped": 0, "total": 2}}


@app.get("/api/app/edit/data")
def edit_data():
    return {"transactions": [], "dividends": [], "estimatedDividends": [], "snapshots": []}