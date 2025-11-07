from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List
from pathlib import Path
import os

from .db import get_conn
from .db import get_conn
import sqlite3

# ---- CONFIG ----
APP_ROOT = Path(__file__).resolve().parents[1]  # project root (where index.html lives)
ASSETS_DIR = APP_ROOT / "assets" / "cards"  # where your PNGs live

API = FastAPI(title="Card API (FastAPI, existing SQLite)")
API.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000", "https://arcana-forge-frontend.onrender.com", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- STOCK TABLE CREATION ----
def derive_price_qty(name: str, seed_extra: int = 0) -> tuple[float, int]:
    """
    Generates a deterministic placeholder price & quantity based on name/id.
    """
    base = sum(ord(c) for c in name) + seed_extra
    r = (abs((base * 9301 + 49297) % 233280) / 233280.0)
    price = round(0.5 + r * 9.5, 2)   # 0.5 .. 10.0g
    qty = max(1, int(1 + r * 20))     # 1 .. 20
    return price, qty

def ensure_stock_schema():
    with get_conn() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS card_stock(
            card_id INTEGER PRIMARY KEY REFERENCES cards(id) ON DELETE CASCADE,
            quantity INTEGER NOT NULL DEFAULT 0,
            price REAL NOT NULL DEFAULT 1.0
        );
        """)
def _norm_name(name: str) -> str:
    # collapse internal spaces and lowercase – "A   day  in the desert" == "a day in the desert"
    return " ".join((name or "").split()).strip().lower()

def dedupe_cards():
    """
    Merge duplicate cards (case-insensitive, whitespace-collapsed names).
    - Keep the smallest id in each duplicate group as the 'master'.
    - Sum quantities from all duplicates into the master.
    - Keep master's existing price if present, else default 1.0.
    - Delete other duplicate rows (card_stock rows will cascade-delete).
    """
    with get_conn() as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        # Get all cards (id, name)
        rows = cur.execute("SELECT id, name FROM cards").fetchall()

        # Group ids by normalized name
        groups = {}
        for r in rows:
            key = _norm_name(r["name"])
            groups.setdefault(key, []).append(r["id"])

        for key, ids in groups.items():
            if len(ids) <= 1:
                continue

            ids.sort()
            master = ids[0]
            others = ids[1:]

            # Total quantity across group
            placeholders = ",".join("?" * len(ids))
            total_qty = cur.execute(
                f"SELECT COALESCE(SUM(quantity),0) FROM card_stock WHERE card_id IN ({placeholders})",
                ids
            ).fetchone()[0]

            # Master's current qty
            master_qty = cur.execute(
                "SELECT COALESCE(quantity,0) FROM card_stock WHERE card_id = ?",
                (master,)
            ).fetchone()
            master_qty = master_qty[0] if master_qty else 0

            delta = total_qty - master_qty

            # Ensure master has a stock row; keep its price if it exists, else 1.0
            price_row = cur.execute("SELECT price FROM card_stock WHERE card_id = ?", (master,)).fetchone()
            price_val = float(price_row["price"]) if (price_row and price_row["price"] is not None) else 1.0

            cur.execute(
                """
                INSERT INTO card_stock(card_id, quantity, price)
                VALUES(?, ?, ?)
                ON CONFLICT(card_id) DO UPDATE SET
                  quantity = card_stock.quantity + excluded.quantity
                """,
                (master, max(delta, 0), price_val)
            )

            # Delete duplicate cards (their card_stock will cascade)
            cur.executemany("DELETE FROM cards WHERE id = ?", [(i,) for i in others])

        con.commit()
def seed_missing_stock():
    with get_conn() as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        rows = cur.execute("""
            SELECT c.id, c.name
            FROM cards c
            LEFT JOIN card_stock s ON s.card_id = c.id
            WHERE s.card_id IS NULL
        """).fetchall()

        for r in rows:
            price, qty = derive_price_qty(r["name"], r["id"])
            cur.execute(
                "INSERT INTO card_stock(card_id, quantity, price) VALUES(?,?,?)",
                (r["id"], int(qty), float(price))
            )
        con.commit()
def create_name_unique_index():
    """Create case-insensitive uniqueness on cards.name after dedupe."""
    with get_conn() as con:
        con.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_cards_name_nocase
        ON cards(name COLLATE NOCASE);
        """)

ensure_stock_schema()
dedupe_cards()
seed_missing_stock()
create_name_unique_index()



# ---- SCHEMA MODELS (match *your* DB columns) ----
# Your DB columns: id, name, card_type, cost, attack, health, tribe, text, keywords_json (ignore)

class CardIn(BaseModel):
    name: str
    card_type: str
    cost: int
    attack: Optional[int] = None
    health: Optional[int] = None
    tribe: Optional[str] = ""
    text: Optional[str] = ""


class Card(BaseModel):
    id: int
    name: str
    card_type: str
    cost: int
    attack: int
    health: int
    tribe: str
    text: str
    # Derived / convenience fields for the UI (not stored in DB):
    image: str
    price: float
    quantity: int


# ---- Helpers: derive image/price/qty for UI ----

def _clean(s: str) -> str:
    return " ".join(s.strip().split())


def guess_image_path(name: str) -> str:
    """Try to find a matching PNG in assets/cards by name.
    Fallback: assets/cards/placeholder.png (create one if you like).
    """
    if not ASSETS_DIR.exists():
        return "assets/cards/placeholder.png"

    target = _clean(name).lower()

    # 1) Exact filename: "<name>.png"
    exact = ASSETS_DIR / f"{_clean(name)}.png"
    if exact.exists():
        return str(Path("assets/cards") / exact.name).replace("\\", "/")

    # 2) Case-insensitive scan of all PNGs
    for p in ASSETS_DIR.glob("*.png"):
        if p.stem.lower() == target:
            return str(Path("assets/cards") / p.name).replace("\\", "/")

    # 3) Loose match: ignore spaces/underscores/dashes
    loose = target.replace(" ", "").replace("_", "").replace("-", "")
    for p in ASSETS_DIR.glob("*.png"):
        stem = p.stem.lower().replace(" ", "").replace("_", "").replace("-", "")
        if stem == loose:
            return str(Path("assets/cards") / p.name).replace("\\", "/")

    return "assets/cards/placeholder.png"


def derive_price_qty(name: str, seed_extra: int = 0) -> tuple[float, int]:
    # stable pseudo-random based on name length + extras
    base = sum(ord(c) for c in name) + seed_extra
    r = (abs((base * 9301 + 49297) % 233280) / 233280.0)
    price = round(0.5 + r * 9.5, 2)  # 0.5 .. 10.0
    qty = max(1, int(1 + r * 20))  # 1 .. 20
    return price, qty


def row_to_card(row) -> Card:
    name = row["name"]
    image = guess_image_path(name)

    # Prefer stored stock; fallback to generated placeholders
    if row["stock_qty"] is not None and row["stock_price"] is not None:
        quantity = int(row["stock_qty"])
        price = float(row["stock_price"])
    else:
        price, quantity = derive_price_qty(name, row["id"])

    return Card(
        id=row["id"],
        name=name,
        card_type=row["card_type"],
        cost=row["cost"],
        attack=row["attack"],
        health=row["health"],
        tribe=row["tribe"],
        text=row["text"],
        image=image,
        price=price,
        quantity=quantity,
    )


# ---- Routes ----

@API.get("/api/cards", response_model=List[Card])
def list_cards(q: Optional[str] = None):
    with get_conn() as con:
        cur = con.cursor()
        if q:
            qlike = f"%{q.lower()}%"
            cur.execute(
                """
                SELECT
                  c.id,
                  COALESCE(c.name,'')        AS name,
                  COALESCE(c.card_type,'')   AS card_type,
                  COALESCE(c.cost,0)         AS cost,
                  COALESCE(c.attack,0)       AS attack,
                  COALESCE(c.health,0)       AS health,
                  COALESCE(c.tribe,'')       AS tribe,
                  COALESCE(c.text,'')        AS text,
                  s.quantity                 AS stock_qty,
                  s.price                    AS stock_price
                FROM cards c
                LEFT JOIN card_stock s ON s.card_id = c.id
                WHERE
                  lower(COALESCE(c.name,'')) LIKE ?
                  OR lower(COALESCE(c.card_type,'')) LIKE ?
                  OR lower(COALESCE(c.tribe,'')) LIKE ?
                ORDER BY c.name ASC
                """,
                (qlike, qlike, qlike)
            )
        else:
            cur.execute(
                """
                SELECT
                  c.id,
                  COALESCE(c.name,'')        AS name,
                  COALESCE(c.card_type,'')   AS card_type,
                  COALESCE(c.cost,0)         AS cost,
                  COALESCE(c.attack,0)       AS attack,
                  COALESCE(c.health,0)       AS health,
                  COALESCE(c.tribe,'')       AS tribe,
                  COALESCE(c.text,'')        AS text,
                  s.quantity                 AS stock_qty,
                  s.price                    AS stock_price
                FROM cards c
                LEFT JOIN card_stock s ON s.card_id = c.id
                ORDER BY c.name ASC
                """
            )

        rows = cur.fetchall()
        return [row_to_card(r) for r in rows]


@API.get("/api/cards/{card_id}", response_model=Card)
def get_card(card_id: int):
    with get_conn() as con:
        cur = con.cursor()
        cur.execute(
            """
            SELECT
              c.id,
              COALESCE(c.name,'')        AS name,
              COALESCE(c.card_type,'')   AS card_type,
              COALESCE(c.cost,0)         AS cost,
              COALESCE(c.attack,0)       AS attack,
              COALESCE(c.health,0)       AS health,
              COALESCE(c.tribe,'')       AS tribe,
              COALESCE(c.text,'')        AS text,
              s.quantity                 AS stock_qty,
              s.price                    AS stock_price
            FROM cards c
            LEFT JOIN card_stock s ON s.card_id = c.id
            WHERE c.id = ?
            """,
            (card_id,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Card not found")
        return row_to_card(row)


@API.post("/api/cards", response_model=Card, status_code=201)
def create_card(card: CardIn):
    name = card.name.strip()
    ctype = (card.card_type or "").strip()

    # If it's a Spell, force stats to 0 no matter what was sent
    attack = 0 if ctype.lower() == "spell" else int(card.attack or 0)
    health = 0 if ctype.lower() == "spell" else int(card.health or 0)

    with get_conn() as con:
        cur = con.cursor()

        # 1) Do we already have a card with this name (case-insensitive)?
        cur.execute("SELECT id FROM cards WHERE name = ? COLLATE NOCASE", (name,))
        row = cur.fetchone()
        if row:
            card_id = row["id"]
            # increment quantity in stock for that existing card
            cur.execute("SELECT quantity, price FROM card_stock WHERE card_id = ?", (card_id,))
            s = cur.fetchone()
            if s:
                cur.execute("UPDATE card_stock SET quantity = quantity + 1 WHERE card_id = ?", (card_id,))
            else:
                # first time we stock this card: choose a price and set qty=1
                price, _ = derive_price_qty(name, card_id)
                cur.execute("INSERT INTO card_stock(card_id, quantity, price) VALUES(?,?,?)",
                            (card_id, 1, float(price)))
            con.commit()

            # Return the updated card (using the JOIN)
            cur.execute("""
                SELECT
                  c.id,
                  COALESCE(c.name,'')      AS name,
                  COALESCE(c.card_type,'') AS card_type,
                  COALESCE(c.cost,0)       AS cost,
                  COALESCE(c.attack,0)     AS attack,
                  COALESCE(c.health,0)     AS health,
                  COALESCE(c.tribe,'')     AS tribe,
                  COALESCE(c.text,'')      AS text,
                  s.quantity               AS stock_qty,
                  s.price                  AS stock_price
                FROM cards c
                LEFT JOIN card_stock s ON s.card_id = c.id
                WHERE c.id = ?
            """, (card_id,))
            return row_to_card(cur.fetchone())

        # 2) New card name → insert into cards and create stock row with qty=1
        cur.execute("""
            INSERT INTO cards (name, card_type, cost, attack, health, tribe, text)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (name, ctype, int(card.cost), attack, health, (card.tribe or "").strip(), (card.text or "").strip()))
        new_id = cur.lastrowid

        price, _ = derive_price_qty(name, new_id)
        cur.execute("INSERT INTO card_stock(card_id, quantity, price) VALUES(?,?,?)",
                    (new_id, 1, float(price)))
        con.commit()

        cur.execute("""
            SELECT
              c.id,
              COALESCE(c.name,'')      AS name,
              COALESCE(c.card_type,'') AS card_type,
              COALESCE(c.cost,0)       AS cost,
              COALESCE(c.attack,0)     AS attack,
              COALESCE(c.health,0)     AS health,
              COALESCE(c.tribe,'')     AS tribe,
              COALESCE(c.text,'')      AS text,
              s.quantity               AS stock_qty,
              s.price                  AS stock_price
            FROM cards c
            LEFT JOIN card_stock s ON s.card_id = c.id
            WHERE c.id = ?
        """, (new_id,))
        return row_to_card(cur.fetchone())

@API.get("/healthz")
def healthz():
    return {"ok": True}


