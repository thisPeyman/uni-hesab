from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from hesab.store import Store

APP = Path(__file__).resolve().parent.parent / "app.py"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("HESAB_DATA_DIR", str(tmp_path))
    return AppTest.from_file(str(APP), default_timeout=15).run()


def by_label(elements, label):
    return next(element for element in elements if element.label == label)


def test_onboarding_validation_and_persistence(app, tmp_path):
    assert not app.exception
    by_label(app.text_input, "مبلغ موجودی اولیه (تومان)").set_value("-5")
    by_label(app.button, "شروع حساب").click().run()
    assert app.error
    assert not app.exception
    by_label(app.text_input, "مبلغ موجودی اولیه (تومان)").set_value("۵۰۰٬۰۰۰")
    by_label(app.button, "شروع حساب").click().run()
    assert not app.exception
    assert Store(tmp_path / "personal.sqlite3").balances()["total"] == 500000
    assert app.success


def test_all_demo_pages_render_and_keep_personal_empty(app, tmp_path):
    app.toggle[0].set_value(True).run()
    assert not app.exception
    for page in ["تراکنش‌ها", "بودجه‌ها", "هدف‌ها", "تنظیمات", "نمای کلی"]:
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception, f"Page failed: {page}"
    demo = Store(tmp_path / "demo.sqlite3")
    assert len(demo.transactions()) > 0
    assert Store(tmp_path / "personal.sqlite3").settings() is None
    app.toggle[0].set_value(False).run()
    assert not app.exception
    assert by_label(app.button, "شروع حساب")


def test_transaction_dialog_create_edit_delete(app, tmp_path):
    app.toggle[0].set_value(True).run()
    app.sidebar.radio[0].set_value("تراکنش‌ها").run()
    store = Store(tmp_path / "demo.sqlite3")
    old_count = len(store.transactions())

    # AppTest's full-script rerun dismisses dialogs. Exercise the real form
    # directly; the modal lifecycle is covered by the Chrome smoke check.
    def form_script(path):
        from hesab.store import Store
        from hesab.ui import transaction_form

        transaction_form(Store(path))

    form = AppTest.from_function(form_script, args=(str(store.path),)).run()
    form.text_input(key="new_amount").set_value("12345")
    by_label(form.text_input, "توضیح (اختیاری)").set_value("تراکنش آزمایشی ویژه")
    by_label(form.form_submit_button, "ثبت تراکنش").click().run()
    assert not form.exception
    assert len(store.transactions()) == old_count + 1
    row = store.transactions(search="تراکنش آزمایشی ویژه")[0]

    def edit_script(path, row):
        from hesab.store import Store
        from hesab.ui import transaction_form

        transaction_form(Store(path), row, prefix="edit_test")

    form = AppTest.from_function(edit_script, args=(str(store.path), row)).run()
    form.text_input(key="edit_test_amount").set_value("54321")
    by_label(form.form_submit_button, "ذخیره تغییرات").click().run()
    assert not form.exception
    assert store.transactions(search="تراکنش آزمایشی ویژه")[0]["amount"] == 54321
    app.run()
    app.button(key=f"edit_button_{row['id']}").click().run()
    assert by_label(app.button, "حذف تراکنش").disabled
    # Store deletion is unit-tested; assert modal confirmation defaults safe.
    store.delete_transaction(row["id"])
    assert len(store.transactions()) == old_count


def test_budget_form_and_goal_allocation(app, tmp_path):
    app.toggle[0].set_value(True).run()
    app.sidebar.radio[0].set_value("بودجه‌ها").run()
    by_label(app.text_input, "سقف (تومان)").set_value("987654")
    by_label(app.button, "ذخیره بودجه").click().run()
    assert not app.exception
    store = Store(tmp_path / "demo.sqlite3")
    assert store.query("SELECT amount FROM budget_rules WHERE amount=987654")
    app.sidebar.radio[0].set_value("هدف‌ها").run()
    goal = store.goals()[0]
    before = store.balances()
    app.text_input(key=f"goal_amount_{goal['id']}").set_value("1000")
    by_label(app.button, "ثبت تخصیص / آزادسازی").click().run()
    assert not app.exception
    assert store.balances()["reserved"] == before["reserved"] + 1000
    assert store.balances()["total"] == before["total"]
