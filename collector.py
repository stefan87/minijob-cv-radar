"""Minijob collector za postojeći config.json i web/template.html."""

import argparse
import base64
import html
import ipaddress
import json
import math
import re
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


BASE = (
    "https://rest.arbeitsagentur.de"
    "/jobboerse/jobsuche-service"
)

SEARCH_ENDPOINTS = (
    "/pc/v6/jobs",
    "/pc/v4/app/jobs",
)

SESSION = requests.Session()
SESSION.headers.update({
    "X-API-Key": "jobboerse-jobsuche",
    "User-Agent": "PersonalMinijobFinder/1.1",
    "Accept": "application/json",
})
