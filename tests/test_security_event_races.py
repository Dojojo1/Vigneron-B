"""Une invalidation Discord reçue ne doit pas être effacée par un ancien fetch."""
import asyncio
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from backend.app import create_app
from backend.config import Settings
from conftest import EMPLOYEE, GUILD, MEMBER, FakeDiscord


