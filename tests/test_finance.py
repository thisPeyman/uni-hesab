import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import timedelta

import pytest

from hesab.dates import (
    jalali,
    month_bounds,
    month_key,
    parse_jalali,
    shift_month,
    today,
)
from hesab.store import FinanceError, Store, amount_value, seed_demo


@pytest.fixture
def store(tmp_path):
    db = Store(tmp_path / "personal.sqlite3")
    db.setup(today() - timedelta(days=400), 10_000)
    return db


def category(store, kind="expense"):
    return store.categories(kind)[0]["id"]


@pytest.mark.parametrize("text,expected", [("۱٬۲۳۴", 1234), ("١٢٣", 123), ("12,000", 12000)])
def test_amount_input(text, expected):
    assert amount_value(text) == expected


@pytest.mark.parametrize("value", ["1.5", "-1", "0", "", "abc", "1e6", "999999999999999999999"])
def test_invalid_amounts(value):
    with pytest.raises(FinanceError):
        amount_value(value)


def test_jalali_leap_and_year_boundary():
    start, end = month_bounds("1399-12")
    assert (end - start).days == 30
    assert jalali(end) == "1400/01/01"
    assert (month_bounds("1400-12")[1] - month_bounds("1400-12")[0]).days == 29
    assert shift_month("1403-01", -1) == "1402-12"
    assert shift_month("1403-12", 1) == "1404-01"
    assert parse_jalali("۱۳۹۹/۱۲/۳۰") == end - timedelta(days=1)
    with pytest.raises(ValueError):
        parse_jalali("1400/12/30")


def test_balance_and_transaction_crud(store):
    store.save_transaction(today(), "income", 1000, category(store, "income"), "درآمد")
    store.save_transaction(today(), "expense", 2000, category(store), "خرید")
    assert store.balances() == {"total": 9000, "reserved": 0, "available": 9000}
    row = store.transactions(search="خرید")[0]
    store.save_transaction(today(), "expense", 3000, category(store), "ویرایش", row["id"])
    assert store.balances()["total"] == 8000
    store.delete_transaction(row["id"])
    assert store.balances()["total"] == 11000


def test_date_and_category_constraints(store):
    with pytest.raises(FinanceError):
        store.save_transaction(today() + timedelta(days=1), "expense", 1, category(store))
    with pytest.raises(FinanceError):
        store.save_transaction(today() - timedelta(days=401), "expense", 1, category(store))
    with pytest.raises(FinanceError):
        store.save_transaction(today(), "income", 1, category(store))
    store.archive_category(category(store), True)
    with pytest.raises(FinanceError):
        store.save_transaction(today(), "expense", 1, category(store, "income"))


def test_archive_preserves_history_and_allows_existing_edit(store):
    initial_count = len(store.categories(active_only=False))
    cid = category(store)
    store.save_transaction(today(), "expense", 50, cid)
    row = store.transactions()[0]
    store.archive_category(cid, True)
    assert cid not in [c["id"] for c in store.categories()]
    assert store.transactions()[0]["category_id"] == cid
    store.save_transaction(today(), "expense", 60, cid, transaction_id=row["id"])
    with pytest.raises(FinanceError):
        store.save_transaction(today(), "expense", 50, cid)
    store.save_category("نام تازه", "expense", cid)
    assert store.transactions()[0]["category"] == "نام تازه"
    reopened = Store(store.path)
    assert len(reopened.categories(active_only=False)) == initial_count
    assert reopened.categories(active_only=False)[0]["name"] == "نام تازه"


def test_goal_allocation_not_expense_and_shortfalls_allowed(store):
    store.save_goal("هدف", 15000, None)
    gid = store.goals()[0]["id"]
    store.move_goal_money(gid, 8000)
    assert store.balances() == {"total": 10000, "reserved": 8000, "available": 2000}
    assert store.transactions() == []
    with pytest.raises(FinanceError):
        store.move_goal_money(gid, 3000)
    store.save_transaction(today(), "expense", 12000, category(store))
    assert store.balances() == {"total": -2000, "reserved": 8000, "available": -10000}
    with pytest.raises(FinanceError):
        store.close_goal(gid, completed=True)
    with pytest.raises(FinanceError):
        store.move_goal_money(gid, 9000, release=True)
    store.move_goal_money(gid, 8000, release=True)
    store.close_goal(gid, completed=True)
    assert store.goals()[0]["status"] == "completed"
    assert len(store.goal_history(gid)) == 2


def test_goal_target_constraints(store):
    store.save_goal("هدف", 5000, None)
    gid = store.goals()[0]["id"]
    store.move_goal_money(gid, 4000)
    with pytest.raises(FinanceError):
        store.move_goal_money(gid, 2000)
    with pytest.raises(FinanceError):
        store.save_goal("هدف", 3000, None, gid)


def test_concurrent_allocations_do_not_overdraw(store):
    store.save_goal("الف", 20000, None)
    store.save_goal("ب", 20000, None)

    def allocate(gid):
        try:
            store.move_goal_money(gid, 8000)
            return True
        except FinanceError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(allocate, [g["id"] for g in store.goals()]))
    assert sum(results) == 1
    assert store.balances()["available"] == 2000


def test_budgets_preserve_history_and_monthly_override(store):
    cid = category(store)
    store.save_budget(cid, "1403-12", 1000, ongoing=True)
    store.save_budget(cid, "1404-02", 2000, ongoing=True)
    store.save_budget(cid, "1404-01", 1500, ongoing=False)

    def budget(month):
        return next(b for b in store.budgets(month) if b["id"] == cid)

    assert budget("1403-11")["limit"] is None
    assert budget("1403-12")["limit"] == 1000
    assert budget("1404-01")["limit"] == 1500
    assert budget("1404-02")["limit"] == 2000
    assert budget("1404-03")["limit"] == 2000
    store.remove_override(cid, "1404-01")
    assert budget("1404-01")["limit"] == 1000
    store.save_budget(cid, "1404-03", 0, ongoing=False)
    assert budget("1404-03")["limit"] == 0


def test_month_filters_use_jalali_boundaries(store):
    current_month = month_key(today())
    start, _ = month_bounds(current_month)
    store.save_transaction(start - timedelta(days=1), "expense", 10, category(store))
    store.save_transaction(start, "expense", 20, category(store))
    assert [r["amount"] for r in store.transactions(month=current_month)] == [20]
    assert (
        next(b for b in store.budgets(current_month) if b["id"] == category(store))["spent"] == 20
    )


def test_backup_and_csv(store, tmp_path):
    store.save_transaction(today(), "expense", 20, category(store), '=HYPERLINK("bad")')
    data = store.export_csv().decode("utf-8-sig")
    assert "'=HYPERLINK" in data
    assert jalali(today()) in data
    backup = tmp_path / "backup.sqlite3"
    backup.write_bytes(store.backup())
    with closing(sqlite3.connect(backup)) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT amount FROM transactions").fetchone()[0] == 20


def test_demo_is_separate_and_seed_is_idempotent(store, tmp_path):
    demo = Store(tmp_path / "demo.sqlite3")
    seed_demo(demo)
    count = len(demo.transactions())
    seed_demo(demo)
    assert len(demo.transactions()) == count > 0
    assert store.transactions() == []
    assert store.balances()["total"] == 10000
