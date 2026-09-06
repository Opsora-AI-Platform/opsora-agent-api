"""Minimal, dependency-free Shopify webhook receiver for the production gateway."""
import base64
import hashlib
import hmac
import os
import sqlite3
import time
import uuid
from http.server import BaseHTTPRequestHandler

SHOPIFY_WEBHOOK_SECRET = os.getenv("SHOPIFY_WEBHOOK_SECRET", "")
SHOPIFY_SHOP_DOMAIN = os.getenv("SHOPIFY_SHOP_DOMAIN", "").strip().lower()
DB_PATH = os.getenv("DB_PATH", "opsora_usage.db")


def _init_shopify_table() -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS shopify_webhook_events (
            id TEXT PRIMARY KEY, event_id TEXT NOT NULL UNIQUE, topic TEXT NOT NULL,
            shop_domain TEXT NOT NULL, payload_hash TEXT NOT NULL, status TEXT NOT NULL,
            received_at REAL NOT NULL, processed_at REAL)""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shopify_webhook_topic ON shopify_webhook_events(topic)")
        conn.commit()
    finally:
        conn.close()


def handle_shopify_webhook(handler: BaseHTTPRequestHandler, body: bytes) -> tuple[int, dict]:
    if not SHOPIFY_WEBHOOK_SECRET:
        return 503, {"error": "Webhook is not configured"}
    signature = handler.headers.get("X-Shopify-Hmac-Sha256", "")
    event_id = handler.headers.get("X-Shopify-Event-Id", "")
    topic = handler.headers.get("X-Shopify-Topic", "unknown")
    shop_domain = handler.headers.get("X-Shopify-Shop-Domain", "").strip().lower()
    if not signature:
        return 401, {"error": "Missing signature"}
    if not event_id:
        return 400, {"error": "Missing event id"}
    if SHOPIFY_SHOP_DOMAIN and shop_domain != SHOPIFY_SHOP_DOMAIN:
        return 403, {"error": "Unknown shop"}
    digest = hmac.new(SHOPIFY_WEBHOOK_SECRET.encode(), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("ascii")
    if not hmac.compare_digest(expected, signature):
        return 401, {"error": "Invalid signature"}
    _init_shopify_table()
    payload_hash = hashlib.sha256(body).hexdigest()
    conn = sqlite3.connect(DB_PATH)
    try:
        existing = conn.execute("SELECT topic FROM shopify_webhook_events WHERE event_id=?", (event_id,)).fetchone()
        if existing:
            return 200, {"status":"received","provider":"shopify","topic":existing[0],"event_id":event_id,"duplicate":True}
        now = time.time()
        conn.execute("INSERT INTO shopify_webhook_events (id,event_id,topic,shop_domain,payload_hash,status,received_at,processed_at) VALUES (?,?,?,?,?,?,?,?)",
                     (str(uuid.uuid4()), event_id, topic, shop_domain, payload_hash, "processed", now, now))
        conn.commit()
    finally:
        conn.close()
    return 200, {"status":"received","provider":"shopify","topic":topic,"event_id":event_id}
