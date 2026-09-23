"""Local web application."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Flask, render_template


def create_app(config: dict[str, Any], config_path: Path) -> Flask:
    """Create the local application without starting a server."""

    app = Flask(__name__)
    app.config["ASSISTANT_CONFIG"] = config
    app.config["ASSISTANT_CONFIG_PATH"] = config_path

    @app.get("/")
    def index() -> str:
        return render_template(
            "index.html",
            sources=config["sources"],
            config_path=config_path,
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app

