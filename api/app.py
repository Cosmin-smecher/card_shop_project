from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List
from pathlib import Path
import os

from .db import get_conn

# ---- CONFIG ----
APP_ROOT = Path(__file__).resolve().parents[1]  # project root (where index.html lives)
ASSETS_DIR = APP_ROOT / "assets" / "cards"     # where your PNGs live

API = FastAPI(title="Card API (FastAPI, existing SQLite)")
API.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000","https://arcana-forge-frontend.onrender.com", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- SCHEMA MODELS (match *your* DB columns) ----
# Your DB columns: id, name, card_type, cost, attack, health, tribe, text, keywords_json (ignore)

class CardIn(BaseModel):
    name: str
    card_type: str
    cost: int = Field(ge=0)
    attack: int = Field(ge=0)
    health: int = Field(ge=0)
    tribe: str
    text: str

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
        return str(Path("assets/cards") / exact.name).replace("\\","/")

    # 2) Case-insensitive scan of all PNGs
    for p in ASSETS_DIR.glob("*.png"):
        if p.stem.lower() == target:
            return str(Path("assets/cards") / p.name).replace("\\","/")

    # 3) Loose match: ignore spaces/underscores/dashes
    loose = target.replace(" ", "").replace("_", "").replace("-", "")
    for p in ASSETS_DIR.glob("*.png"):
        stem = p.stem.lower().replace(" ", "").replace("_", "").replace("-", "")
        if stem == loose:
            return str(Path("assets/cards") / p.name).replace("\\","/")

    return "assets/cards/placeholder.png"


def derive_price_qty(name: str, seed_extra: int = 0) -> tuple[float, int]:
    # stable pseudo-random based on name length + extras
    base = sum(ord(c) for c in name) + seed_extra
    r = (abs((base * 9301 + 49297) % 233280) / 233280.0)
    price = round(0.5 + r * 9.5, 2)  # 0.5 .. 10.0
    qty = max(1, int(1 + r * 20))    # 1 .. 20
    return price, qty


def row_to_card(row) -> Card:
    name = row["name"]
    image = guess_image_path(name)
    price, qty = derive_price_qty(name, row["id"])
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
        quantity=qty,
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
                  id,
                  COALESCE(name, '')        AS name,
                  COALESCE(card_type, '')   AS card_type,
                  COALESCE(cost, 0)         AS cost,
                  COALESCE(attack, 0)       AS attack,
                  COALESCE(health, 0)       AS health,
                  COALESCE(tribe, '')       AS tribe,
                  COALESCE(text, '')        AS text
                FROM cards
                WHERE lower(COALESCE(name, '')) LIKE ?
                   OR lower(COALESCE(card_type, '')) LIKE ?
                   OR lower(COALESCE(tribe, '')) LIKE ?
                ORDER BY name ASC
                """,
                (qlike, qlike, qlike),
            )
        else:
            cur.execute(
                """
                SELECT
                  id,
                  COALESCE(name, '')        AS name,
                  COALESCE(card_type, '')   AS card_type,
                  COALESCE(cost, 0)         AS cost,
                  COALESCE(attack, 0)       AS attack,
                  COALESCE(health, 0)       AS health,
                  COALESCE(tribe, '')       AS tribe,
                  COALESCE(text, '')        AS text
                FROM cards
                ORDER BY name ASC
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
              id,
              COALESCE(name, '')        AS name,
              COALESCE(card_type, '')   AS card_type,
              COALESCE(cost, 0)         AS cost,
              COALESCE(attack, 0)       AS attack,
              COALESCE(health, 0)       AS health,
              COALESCE(tribe, '')       AS tribe,
              COALESCE(text, '')        AS text
            FROM cards
            WHERE id=?
            """,
            (card_id,),
        )

        row = cur.fetchone()
        if not row:
            raise HTTPException(404, detail="Card not found")
        return row_to_card(row)

@API.post("/api/cards", response_model=Card, status_code=201)
def create_card(card: CardIn):
    with get_conn() as con:
        cur = con.cursor()
        cur.execute(
            """
            INSERT INTO cards (name, card_type, cost, attack, health, tribe, text)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                card.name.strip(),
                card.card_type.strip(),
                int(card.cost),
                int(card.attack),
                int(card.health),
                card.tribe.strip(),
                card.text.strip(),
            ),
        )
        new_id = cur.lastrowid
        con.commit()
        # Fetch the newly created row
        cur.execute(
            "SELECT id, name, card_type, cost, attack, health, tribe, text FROM cards WHERE id=?",
            (new_id,),
        )
        row = cur.fetchone()
        return row_to_card(row)

@API.get("/healthz")
def healthz():
    return {"ok": True}

# Run with: uvicorn api.app:API --reload --port 5001
