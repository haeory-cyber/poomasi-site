#!/usr/bin/env python3
"""시민재생에너지 AI 사이트 서버 (energy.poomasi.org) — 정적 서빙

sakyowon/server.py 패턴을 따른 경량 정적 서버. 현재는 소개·비전 랜딩(정적)만
제공한다. 향후 문의 폼·AI 기능이 필요해지면 sakyowon/server.py의 /api/* 라우트를
참고해 확장한다.
"""

from pathlib import Path

from flask import Flask, send_from_directory

STATIC_DIR = Path(__file__).resolve().parent

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(STATIC_DIR, path)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8050, debug=False)
