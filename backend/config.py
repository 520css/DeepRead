"""Pydantic Settings: reads config.yaml from paperbridge/ root."""

import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

_ROOT = Path(__file__).resolve().parent.parent  # paperbridge/

_CFG_PATH = _ROOT / "config.yaml"
if not _CFG_PATH.exists():
    raise FileNotFoundError(f"config.yaml not found at {_CFG_PATH}")

with open(_CFG_PATH, "r", encoding="utf-8") as f:
    _CFG = yaml.safe_load(f)


def get_llm_config() -> dict:
    return _CFG.get("llm", {})


def get_budget_config() -> dict:
    return _CFG.get("budget", {})


def get_profile_config() -> dict:
    return _CFG.get("profile", {})


def get_embedding_config() -> dict:
    return _CFG.get("embedding", {})


def get_history_config() -> dict:
    return _CFG.get("history", {})


def get_reading_config() -> dict:
    return _CFG.get("reading", {})
