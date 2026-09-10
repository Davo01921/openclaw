"""SQLite registry for NTA Gumtree automation.

Phase 2 registry only. This module records deterministic local state and does not
call Shopify, Gumtree, browser automation, or any language model.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

SCHEMA_VERSION = 1

ACTUAL_STATES = {
    "UNKNOWN",
    "MISSING",
    "DRAFT",
    "ACTIVE",
    "PAUSED",
    "EXPIRED",
    "SOLD",
    "REMOVED",
    "ERROR",
    "NEEDS_REVIEW",
}

MANAGEMENT_STATES = {
    "DISCOVERED",
    "IDENTIFIED",
    "MAPPED",
    "MANAGED",
    "RETIRED",
    "NEEDS_REVIEW",
}

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS products (
    shopify_product_id TEXT PRIMARY KEY,
    shopify_gid TEXT,
    title TEXT NOT NULL,
    handle TEXT,
    product_type TEXT,
    status TEXT,
    management_state TEXT NOT NULL DEFAULT 'DISCOVERED'
        CHECK (management_state IN ('DISCOVERED','IDENTIFIED','MAPPED','MANAGED','RETIRED','NEEDS_REVIEW')),
    config_state TEXT,
    policy TEXT,
    priority TEXT,
    availability_status TEXT,
    content_fingerprint TEXT,
    last_shopify_seen_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS advertisements (
    ad_id TEXT PRIMARY KEY,
    ad_kind TEXT NOT NULL DEFAULT 'STANDARD',
    lifecycle_state TEXT,
    desired_listing_count INTEGER NOT NULL DEFAULT 1 CHECK (desired_listing_count >= 0),
    canonical INTEGER NOT NULL DEFAULT 1 CHECK (canonical IN (0,1)),
    title_override TEXT,
    description_override TEXT,
    price_override TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS product_ad_links (
    shopify_product_id TEXT NOT NULL,
    ad_id TEXT NOT NULL,
    relationship TEXT NOT NULL DEFAULT 'PRIMARY',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (shopify_product_id, ad_id),
    FOREIGN KEY (shopify_product_id) REFERENCES products(shopify_product_id) ON DELETE RESTRICT,
    FOREIGN KEY (ad_id) REFERENCES advertisements(ad_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS gumtree_instances (
    instance_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ad_id TEXT NOT NULL,
    gumtree_listing_id TEXT UNIQUE,
    url TEXT,
    actual_state TEXT NOT NULL DEFAULT 'UNKNOWN'
        CHECK (actual_state IN ('UNKNOWN','MISSING','DRAFT','ACTIVE','PAUSED','EXPIRED','SOLD','REMOVED','ERROR','NEEDS_REVIEW')),
    is_canonical INTEGER NOT NULL DEFAULT 0 CHECK (is_canonical IN (0,1)),
    title TEXT,
    price TEXT,
    content_fingerprint TEXT,
    image_fingerprint TEXT,
    first_seen_at TEXT,
    last_seen_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ad_id) REFERENCES advertisements(ad_id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_one_canonical_live_instance_per_ad
ON gumtree_instances(ad_id)
WHERE is_canonical = 1 AND actual_state IN ('DRAFT','ACTIVE','PAUSED');

CREATE INDEX IF NOT EXISTS ix_gumtree_instances_ad_id
ON gumtree_instances(ad_id);

CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    instance_id INTEGER,
    captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    views INTEGER,
    favourites INTEGER,
    enquiries INTEGER,
    payload_json TEXT,
    FOREIGN KEY (instance_id) REFERENCES gumtree_instances(instance_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS actions (
    action_id INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT NOT NULL UNIQUE,
    run_id TEXT,
    shopify_product_id TEXT,
    ad_id TEXT,
    instance_id INTEGER,
    action TEXT NOT NULL,
    reason_code TEXT,
    status TEXT NOT NULL DEFAULT 'PLANNED',
    payload_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    FOREIGN KEY (shopify_product_id) REFERENCES products(shopify_product_id) ON DELETE RESTRICT,
    FOREIGN KEY (ad_id) REFERENCES advertisements(ad_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id) REFERENCES gumtree_instances(instance_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    run_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'RUNNING',
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    error_count INTEGER NOT NULL DEFAULT 0,
    warning_count INTEGER NOT NULL DEFAULT 0,
    summary_json TEXT
);
"""


def _json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class Registry:
    db_path: Path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
                (SCHEMA_VERSION,),
            )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def upsert_product(self, product: Mapping[str, Any]) -> None:
        product_id = str(product["shopify_product_id"])
        management_state = product.get("management_state", "DISCOVERED")
        if management_state not in MANAGEMENT_STATES:
            raise ValueError(f"invalid management_state: {management_state}")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO products(
                    shopify_product_id, shopify_gid, title, handle, product_type,
                    status, management_state, config_state, policy, priority,
                    availability_status, content_fingerprint, last_shopify_seen_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(shopify_product_id) DO UPDATE SET
                    shopify_gid=excluded.shopify_gid,
                    title=excluded.title,
                    handle=excluded.handle,
                    product_type=excluded.product_type,
                    status=excluded.status,
                    management_state=excluded.management_state,
                    config_state=excluded.config_state,
                    policy=excluded.policy,
                    priority=excluded.priority,
                    availability_status=excluded.availability_status,
                    content_fingerprint=excluded.content_fingerprint,
                    last_shopify_seen_at=excluded.last_shopify_seen_at,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    product_id,
                    product.get("shopify_gid"),
                    str(product.get("title", "")),
                    product.get("handle"),
                    product.get("product_type"),
                    product.get("status"),
                    management_state,
                    product.get("config_state"),
                    product.get("policy"),
                    product.get("priority"),
                    product.get("availability_status"),
                    product.get("content_fingerprint"),
                    product.get("last_shopify_seen_at"),
                ),
            )

    def get_product(self, shopify_product_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM products WHERE shopify_product_id = ?",
                (str(shopify_product_id),),
            ).fetchone()
        return dict(row) if row else None

    def upsert_advertisement(self, ad: Mapping[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO advertisements(
                    ad_id, ad_kind, lifecycle_state, desired_listing_count,
                    canonical, title_override, description_override, price_override
                ) VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(ad_id) DO UPDATE SET
                    ad_kind=excluded.ad_kind,
                    lifecycle_state=excluded.lifecycle_state,
                    desired_listing_count=excluded.desired_listing_count,
                    canonical=excluded.canonical,
                    title_override=excluded.title_override,
                    description_override=excluded.description_override,
                    price_override=excluded.price_override,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    str(ad["ad_id"]),
                    ad.get("ad_kind", "STANDARD"),
                    ad.get("lifecycle_state"),
                    int(ad.get("desired_listing_count", 1)),
                    1 if ad.get("canonical", True) else 0,
                    ad.get("title_override"),
                    ad.get("description_override"),
                    ad.get("price_override"),
                ),
            )

    def link_product_ad(self, shopify_product_id: str, ad_id: str, relationship: str = "PRIMARY") -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO product_ad_links(shopify_product_id, ad_id, relationship) VALUES (?,?,?)",
                (str(shopify_product_id), str(ad_id), relationship),
            )

    def record_instance(self, instance: Mapping[str, Any]) -> int:
        state = instance.get("actual_state", "UNKNOWN")
        if state not in ACTUAL_STATES:
            raise ValueError(f"invalid actual_state: {state}")
        listing_id = instance.get("gumtree_listing_id")
        with self.connect() as conn:
            if listing_id:
                existing = conn.execute(
                    "SELECT instance_id FROM gumtree_instances WHERE gumtree_listing_id = ?",
                    (str(listing_id),),
                ).fetchone()
            else:
                existing = None

            values = (
                str(instance["ad_id"]),
                str(listing_id) if listing_id else None,
                instance.get("url"),
                state,
                1 if instance.get("is_canonical", False) else 0,
                instance.get("title"),
                instance.get("price"),
                instance.get("content_fingerprint"),
                instance.get("image_fingerprint"),
                instance.get("first_seen_at"),
                instance.get("last_seen_at"),
            )
            if existing:
                instance_id = int(existing["instance_id"])
                conn.execute(
                    """
                    UPDATE gumtree_instances SET
                        ad_id=?, gumtree_listing_id=?, url=?, actual_state=?, is_canonical=?,
                        title=?, price=?, content_fingerprint=?, image_fingerprint=?,
                        first_seen_at=COALESCE(first_seen_at, ?), last_seen_at=?, updated_at=CURRENT_TIMESTAMP
                    WHERE instance_id=?
                    """,
                    (*values, instance_id),
                )
                return instance_id

            cursor = conn.execute(
                """
                INSERT INTO gumtree_instances(
                    ad_id, gumtree_listing_id, url, actual_state, is_canonical,
                    title, price, content_fingerprint, image_fingerprint,
                    first_seen_at, last_seen_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                values,
            )
            return int(cursor.lastrowid)

    def list_instances(self, ad_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM gumtree_instances WHERE ad_id = ? ORDER BY instance_id",
                (str(ad_id),),
            ).fetchall()
        return [dict(row) for row in rows]

    def start_run(self, run_id: str, run_type: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO runs(run_id, run_type) VALUES (?,?)",
                (str(run_id), str(run_type)),
            )

    def finish_run(
        self,
        run_id: str,
        status: str,
        *,
        error_count: int = 0,
        warning_count: int = 0,
        summary: Any = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE runs SET status=?, finished_at=CURRENT_TIMESTAMP,
                    error_count=?, warning_count=?, summary_json=?
                WHERE run_id=?
                """,
                (status, int(error_count), int(warning_count), _json(summary), str(run_id)),
            )

    def record_action(
        self,
        *,
        idempotency_key: str,
        action: str,
        run_id: str | None = None,
        shopify_product_id: str | None = None,
        ad_id: str | None = None,
        instance_id: int | None = None,
        reason_code: str | None = None,
        status: str = "PLANNED",
        payload: Any = None,
    ) -> tuple[int, bool]:
        """Record an action once. Returns (action_id, created)."""
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT action_id FROM actions WHERE idempotency_key = ?",
                (str(idempotency_key),),
            ).fetchone()
            if existing:
                return int(existing["action_id"]), False
            cursor = conn.execute(
                """
                INSERT INTO actions(
                    idempotency_key, run_id, shopify_product_id, ad_id,
                    instance_id, action, reason_code, status, payload_json
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(idempotency_key),
                    run_id,
                    shopify_product_id,
                    ad_id,
                    instance_id,
                    action,
                    reason_code,
                    status,
                    _json(payload),
                ),
            )
            return int(cursor.lastrowid), True


def initialize_registry(path: str | Path) -> Registry:
    registry = Registry(Path(path))
    registry.initialize()
    return registry
