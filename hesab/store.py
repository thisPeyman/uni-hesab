"""SQLite persistence and atomic financial operations. No Streamlit dependency."""

import csv
import io
import sqlite3
from contextlib import closing, contextmanager
from datetime import date, timedelta
from pathlib import Path

from hesab.dates import jalali, month_bounds, month_key, shift_month, today

MAX_AMOUNT = 9_000_000_000_000
DEFAULT_CATEGORIES = {
    "expense": [
        "خوراک",
        "رفت‌وآمد",
        "مسکن",
        "خرید",
        "سلامت",
        "آموزش",
        "تفریح",
        "قبوض",
        "سایر هزینه‌ها",
    ],
    "income": ["حقوق", "کار آزاد", "هدیه", "سایر درآمدها"],
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    opening_date TEXT NOT NULL,
    opening_balance INTEGER NOT NULL CHECK (opening_balance >= 0)
);
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('income', 'expense')),
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    UNIQUE (name, kind)
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY,
    occurred_on TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('income', 'expense')),
    amount INTEGER NOT NULL CHECK (amount > 0),
    category_id INTEGER NOT NULL REFERENCES categories(id),
    note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS transactions_date ON transactions(occurred_on);
CREATE TABLE IF NOT EXISTS budget_rules (
    category_id INTEGER NOT NULL REFERENCES categories(id),
    effective_month TEXT NOT NULL,
    amount INTEGER NOT NULL CHECK (amount >= 0),
    PRIMARY KEY (category_id, effective_month)
);
CREATE TABLE IF NOT EXISTS budget_overrides (
    category_id INTEGER NOT NULL REFERENCES categories(id),
    month TEXT NOT NULL,
    amount INTEGER NOT NULL CHECK (amount >= 0),
    PRIMARY KEY (category_id, month)
);
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    target INTEGER NOT NULL CHECK (target > 0),
    deadline TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed', 'archived'))
);
CREATE TABLE IF NOT EXISTS goal_entries (
    id INTEGER PRIMARY KEY,
    goal_id INTEGER NOT NULL REFERENCES goals(id),
    amount INTEGER NOT NULL CHECK (amount != 0),
    created_on TEXT NOT NULL
);
PRAGMA user_version = 1;
"""


class FinanceError(ValueError):
    """An actionable validation failure safe to display to the user."""


def amount_value(value: str | int, *, allow_zero: bool = False) -> int:
    from hesab.dates import latin_digits

    text = latin_digits(str(value)).strip().replace(",", "").replace("٬", "")
    if not text or not text.isascii() or not text.isdigit():
        raise FinanceError("مبلغ باید عدد صحیح و بدون اعشار، به تومان باشد.")
    amount = int(text)
    if amount < (0 if allow_zero else 1) or amount > MAX_AMOUNT:
        raise FinanceError(f"مبلغ باید بین {0 if allow_zero else 1:,} و {MAX_AMOUNT:,} تومان باشد.")
    return amount


def clean_name(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 80:
        raise FinanceError("نام باید بین 1 تا 80 نویسه باشد.")
    return value


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript(SCHEMA)
            if not db.execute("SELECT 1 FROM categories LIMIT 1").fetchone():
                for kind, names in DEFAULT_CATEGORIES.items():
                    db.executemany(
                        "INSERT INTO categories(name, kind) VALUES (?, ?)",
                        [(name, kind) for name in names],
                    )

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            # Serialize check-then-write operations, notably goal allocations.
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        with self.connection() as db:
            return [dict(row) for row in db.execute(sql, params)]

    def settings(self) -> dict | None:
        rows = self.query("SELECT * FROM settings WHERE id = 1")
        return rows[0] if rows else None

    def setup(self, opening_date: date, balance: int) -> None:
        balance = amount_value(balance, allow_zero=True)
        if opening_date > today():
            raise FinanceError("تاریخ شروع نمی‌تواند در آینده باشد.")
        with self.connection() as db:
            if db.execute("SELECT 1 FROM settings").fetchone():
                raise FinanceError("موجودی اولیه قبلاً ثبت شده است.")
            db.execute("INSERT INTO settings VALUES (1, ?, ?)", (opening_date.isoformat(), balance))

    def categories(self, kind: str | None = None, *, active_only: bool = True) -> list[dict]:
        sql, args = "SELECT * FROM categories WHERE 1=1", []
        if kind:
            sql += " AND kind = ?"
            args.append(kind)
        if active_only:
            sql += " AND archived = 0"
        return self.query(sql + " ORDER BY id", tuple(args))

    def save_category(self, name: str, kind: str, category_id: int | None = None) -> None:
        name = clean_name(name)
        if kind not in DEFAULT_CATEGORIES:
            raise FinanceError("نوع دسته معتبر نیست.")
        try:
            with self.connection() as db:
                if category_id is None:
                    db.execute("INSERT INTO categories(name, kind) VALUES (?, ?)", (name, kind))
                elif not db.execute(
                    "UPDATE categories SET name = ? WHERE id = ? AND kind = ?",
                    (name, category_id, kind),
                ).rowcount:
                    raise FinanceError("دسته پیدا نشد.")
        except sqlite3.IntegrityError as exc:
            raise FinanceError("این نام برای این نوع دسته قبلاً ثبت شده است.") from exc

    def archive_category(self, category_id: int, archived: bool) -> None:
        with self.connection() as db:
            db.execute(
                "UPDATE categories SET archived = ? WHERE id = ?", (int(archived), category_id)
            )

    @staticmethod
    def _balances(db: sqlite3.Connection) -> dict:
        setting = db.execute("SELECT opening_balance FROM settings WHERE id = 1").fetchone()
        net = db.execute(
            "SELECT COALESCE(SUM(CASE WHEN kind='income' THEN amount ELSE -amount END), 0) FROM transactions"
        ).fetchone()[0]
        reserved = db.execute("SELECT COALESCE(SUM(amount), 0) FROM goal_entries").fetchone()[0]
        total = (setting[0] if setting else 0) + net
        return {"total": total, "reserved": reserved, "available": total - reserved}

    def balances(self) -> dict:
        with self.connection() as db:
            return self._balances(db)

    def save_transaction(
        self,
        occurred_on: date,
        kind: str,
        amount: int,
        category_id: int,
        note: str = "",
        transaction_id: int | None = None,
    ) -> None:
        amount = amount_value(amount)
        if len(note.strip()) > 300:
            raise FinanceError("توضیح باید حداکثر 300 نویسه باشد.")
        with self.connection() as db:
            setting = db.execute("SELECT opening_date FROM settings WHERE id=1").fetchone()
            if not setting:
                raise FinanceError("ابتدا موجودی اولیه را ثبت کنید.")
            if not date.fromisoformat(setting[0]) <= occurred_on <= today():
                raise FinanceError("تاریخ باید بین تاریخ شروع و امروز باشد.")
            previous = None
            if transaction_id is not None:
                previous = db.execute(
                    "SELECT * FROM transactions WHERE id=?", (transaction_id,)
                ).fetchone()
                if not previous:
                    raise FinanceError("تراکنش پیدا نشد؛ فهرست را تازه کنید.")
            category = db.execute("SELECT * FROM categories WHERE id=?", (category_id,)).fetchone()
            if not category or category["kind"] != kind:
                raise FinanceError("دسته با نوع تراکنش مطابقت ندارد.")
            if category["archived"] and (not previous or previous["category_id"] != category_id):
                raise FinanceError("برای تراکنش جدید از یک دسته فعال استفاده کنید.")
            values = (occurred_on.isoformat(), kind, amount, category_id, note.strip())
            if transaction_id is None:
                db.execute(
                    "INSERT INTO transactions(occurred_on,kind,amount,category_id,note) VALUES (?,?,?,?,?)",
                    values,
                )
            else:
                db.execute(
                    "UPDATE transactions SET occurred_on=?,kind=?,amount=?,category_id=?,note=? WHERE id=?",
                    (*values, transaction_id),
                )

    def delete_transaction(self, transaction_id: int) -> None:
        with self.connection() as db:
            if not db.execute("DELETE FROM transactions WHERE id=?", (transaction_id,)).rowcount:
                raise FinanceError("تراکنش پیدا نشد.")

    def transactions(
        self,
        *,
        month: str | None = None,
        kind: str | None = None,
        category_id: int | None = None,
        search: str = "",
    ) -> list[dict]:
        sql = """SELECT t.*, c.name AS category FROM transactions t
                 JOIN categories c ON c.id=t.category_id WHERE 1=1"""
        args = []
        if month:
            start, end = month_bounds(month)
            sql += " AND t.occurred_on >= ? AND t.occurred_on < ?"
            args.extend([start.isoformat(), end.isoformat()])
        if kind:
            sql += " AND t.kind=?"
            args.append(kind)
        if category_id:
            sql += " AND t.category_id=?"
            args.append(category_id)
        rows = self.query(sql + " ORDER BY t.occurred_on DESC, t.id DESC", tuple(args))
        if search.strip():
            needle = search.strip().casefold()
            rows = [
                r for r in rows if needle in f"{r['note']} {r['category']} {r['amount']}".casefold()
            ]
        return rows

    def save_budget(self, category_id: int, month: str, amount: int, *, ongoing: bool) -> None:
        month_bounds(month)
        amount = amount_value(amount, allow_zero=True)
        with self.connection() as db:
            category = db.execute(
                "SELECT kind FROM categories WHERE id=?", (category_id,)
            ).fetchone()
            if not category or category[0] != "expense":
                raise FinanceError("بودجه فقط برای دسته‌های هزینه است.")
            if ongoing:
                db.execute(
                    "INSERT INTO budget_rules VALUES (?,?,?) ON CONFLICT(category_id,effective_month) DO UPDATE SET amount=excluded.amount",
                    (category_id, month, amount),
                )
            else:
                db.execute(
                    "INSERT INTO budget_overrides VALUES (?,?,?) ON CONFLICT(category_id,month) DO UPDATE SET amount=excluded.amount",
                    (category_id, month, amount),
                )

    def remove_override(self, category_id: int, month: str) -> None:
        with self.connection() as db:
            db.execute(
                "DELETE FROM budget_overrides WHERE category_id=? AND month=?", (category_id, month)
            )

    def budgets(self, month: str) -> list[dict]:
        start, end = month_bounds(month)
        with self.connection() as db:
            result = []
            for category in db.execute(
                "SELECT * FROM categories WHERE kind='expense' ORDER BY id"
            ).fetchall():
                cid = category["id"]
                override = db.execute(
                    "SELECT amount FROM budget_overrides WHERE category_id=? AND month=?",
                    (cid, month),
                ).fetchone()
                rule = db.execute(
                    "SELECT amount FROM budget_rules WHERE category_id=? AND effective_month<=? ORDER BY effective_month DESC LIMIT 1",
                    (cid, month),
                ).fetchone()
                limit = override[0] if override else rule[0] if rule else None
                spent = db.execute(
                    "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE kind='expense' AND category_id=? AND occurred_on>=? AND occurred_on<?",
                    (cid, start.isoformat(), end.isoformat()),
                ).fetchone()[0]
                if not category["archived"] or limit is not None or spent:
                    result.append(
                        {
                            **dict(category),
                            "limit": limit,
                            "spent": spent,
                            "override": override is not None,
                        }
                    )
            return result

    def goals(self) -> list[dict]:
        return self.query("""SELECT g.*, COALESCE(SUM(e.amount),0) AS reserved FROM goals g
            LEFT JOIN goal_entries e ON e.goal_id=g.id GROUP BY g.id ORDER BY g.id DESC""")

    def save_goal(
        self, name: str, target: int, deadline: date | None, goal_id: int | None = None
    ) -> None:
        name, target = clean_name(name), amount_value(target)
        with self.connection() as db:
            if goal_id is None:
                if deadline and deadline < today():
                    raise FinanceError("مهلت هدف جدید نمی‌تواند قبل از امروز باشد.")
                db.execute(
                    "INSERT INTO goals(name,target,deadline) VALUES (?,?,?)",
                    (name, target, deadline.isoformat() if deadline else None),
                )
            else:
                goal = db.execute(
                    "SELECT * FROM goals WHERE id=? AND status='active'", (goal_id,)
                ).fetchone()
                if not goal:
                    raise FinanceError("هدف فعال پیدا نشد.")
                reserved = db.execute(
                    "SELECT COALESCE(SUM(amount),0) FROM goal_entries WHERE goal_id=?", (goal_id,)
                ).fetchone()[0]
                if target < reserved:
                    raise FinanceError("مبلغ هدف نمی‌تواند کمتر از پول کنارگذاشته‌شده باشد.")
                db.execute(
                    "UPDATE goals SET name=?,target=?,deadline=? WHERE id=?",
                    (name, target, deadline.isoformat() if deadline else None, goal_id),
                )

    def move_goal_money(self, goal_id: int, amount: int, *, release: bool = False) -> None:
        amount = amount_value(amount)
        with self.connection() as db:
            goal = db.execute(
                "SELECT * FROM goals WHERE id=? AND status='active'", (goal_id,)
            ).fetchone()
            if not goal:
                raise FinanceError("هدف فعال پیدا نشد.")
            reserved = db.execute(
                "SELECT COALESCE(SUM(amount),0) FROM goal_entries WHERE goal_id=?", (goal_id,)
            ).fetchone()[0]
            if release:
                if amount > reserved:
                    raise FinanceError("مبلغ آزادسازی بیشتر از ذخیره این هدف است.")
            elif amount > self._balances(db)["available"]:
                raise FinanceError("موجودی قابل خرج برای این تخصیص کافی نیست.")
            elif reserved + amount > goal["target"]:
                raise FinanceError("تخصیص بیشتر از مبلغ هدف مجاز نیست.")
            db.execute(
                "INSERT INTO goal_entries(goal_id,amount,created_on) VALUES (?,?,?)",
                (goal_id, -amount if release else amount, today().isoformat()),
            )

    def close_goal(self, goal_id: int, *, completed: bool) -> None:
        with self.connection() as db:
            reserved = db.execute(
                "SELECT COALESCE(SUM(amount),0) FROM goal_entries WHERE goal_id=?", (goal_id,)
            ).fetchone()[0]
            if reserved:
                raise FinanceError("ابتدا تمام پول کنارگذاشته‌شده برای این هدف را آزاد کنید.")
            if not db.execute(
                "UPDATE goals SET status=? WHERE id=? AND status='active'",
                ("completed" if completed else "archived", goal_id),
            ).rowcount:
                raise FinanceError("هدف فعال پیدا نشد.")

    def goal_history(self, goal_id: int) -> list[dict]:
        return self.query("SELECT * FROM goal_entries WHERE goal_id=? ORDER BY id DESC", (goal_id,))

    def export_csv(self) -> bytes:
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["شناسه", "تاریخ شمسی", "نوع", "مبلغ (تومان)", "دسته", "توضیح"])

        def safe(value: str) -> str:
            return (
                "'" + value
                if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n"))
                else value
            )

        for row in self.transactions():
            writer.writerow(
                [
                    row["id"],
                    jalali(row["occurred_on"]),
                    "درآمد" if row["kind"] == "income" else "هزینه",
                    row["amount"],
                    safe(row["category"]),
                    safe(row["note"]),
                ]
            )
        return output.getvalue().encode("utf-8-sig")

    def backup(self) -> bytes:
        # SQLite's backup API gives a consistent snapshot, even while another tab writes.
        with (
            closing(sqlite3.connect(self.path)) as source,
            closing(sqlite3.connect(":memory:")) as target,
        ):
            source.backup(target)
            result = target.serialize()
        return result


def seed_demo(store: Store) -> None:
    """Seed only the dedicated demo store; never touch an initialized database."""
    if store.settings():
        return
    current = today()
    current_month = month_key(current)
    start, _ = month_bounds(current_month)
    previous_start, _ = month_bounds(shift_month(current_month, -1))
    store.setup(previous_start, 18_000_000)
    categories = {(c["kind"], c["name"]): c["id"] for c in store.categories()}
    for base in [previous_start, start]:
        for offset, kind, name, amount, note in [
            (0, "income", "حقوق", 24_000_000, "حقوق ماهانه"),
            (0, "expense", "مسکن", 8_000_000, "اجاره خانه"),
            (0, "expense", "خوراک", 1_250_000, "خرید هفتگی"),
            (2, "expense", "رفت‌وآمد", 380_000, "مترو و تاکسی"),
            (4, "expense", "آموزش", 950_000, "کتاب و دوره آموزشی"),
            (6, "expense", "خوراک", 780_000, "خرید مواد غذایی"),
            (8, "income", "کار آزاد", 3_500_000, "طراحی پروژه"),
            (10, "expense", "تفریح", 620_000, "کافه با دوستان"),
            (12, "expense", "قبوض", 450_000, "اینترنت و تلفن"),
            (16, "expense", "خرید", 1_800_000, "لباس"),
            (21, "expense", "خوراک", 1_100_000, "خرید هفتگی"),
            (25, "expense", "سلامت", 300_000, "داروخانه"),
        ]:
            occurred = base + timedelta(days=offset)
            if occurred <= current:
                store.save_transaction(occurred, kind, amount, categories[kind, name], note)
    for name, limit in [
        ("خوراک", 4_000_000),
        ("مسکن", 8_000_000),
        ("رفت‌وآمد", 1_500_000),
        ("تفریح", 1_000_000),
        ("آموزش", 800_000),
    ]:
        store.save_budget(
            categories["expense", name], month_key(previous_start), limit, ongoing=True
        )
    store.save_goal("لپ‌تاپ جدید", 45_000_000, current + timedelta(days=150))
    store.save_goal("صندوق روز مبادا", 20_000_000, None)
    goals = {g["name"]: g["id"] for g in store.goals()}
    store.move_goal_money(goals["لپ‌تاپ جدید"], 9_000_000)
    store.move_goal_money(goals["صندوق روز مبادا"], 6_000_000)
