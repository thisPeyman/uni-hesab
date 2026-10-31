"""Persian Streamlit presentation; all financial mutations go through Store."""

import os
from datetime import date
from html import escape
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from hesab.dates import jalali, month_key, month_label, parse_jalali, shift_month, today
from hesab.store import FinanceError, Store, amount_value, seed_demo

ROOT = Path(__file__).resolve().parent.parent
KINDS = {"expense": "هزینه", "income": "درآمد"}
PAGES = ["نمای کلی", "تراکنش‌ها", "بودجه‌ها", "هدف‌ها", "تنظیمات"]
PAGE_ICONS = dict(
    zip(PAGES, ["space_dashboard", "receipt_long", "donut_large", "flag", "tune"], strict=True)
)


def money(value: int) -> str:
    return f"{value:,}"


def html(content: str) -> None:
    st.html(content)


def notice(message: str) -> None:
    st.session_state["notice"] = message
    st.rerun()


def heading(title: str, subtitle: str) -> None:
    html(
        f'<div class="page-head"><div><div class="eyebrow">حساب شخصی شما</div>'
        f"<h1>{escape(title)}</h1><p>{escape(subtitle)}</p></div>"
        '<div class="local-badge">محلی و خصوصی</div></div>'
    )


def empty(title: str, instruction: str) -> None:
    html(f'<div class="empty-state"><strong>{escape(title)}</strong>{escape(instruction)}</div>')


def month_picker(store: Store, key: str, *, future: bool = False) -> str:
    setting = store.settings()
    first = (
        month_key(date.fromisoformat(setting["opening_date"])) if setting else month_key(today())
    )
    last = shift_month(month_key(today()), 12 if future else 0)
    months = []
    cursor = last
    while cursor >= first:
        months.append(cursor)
        cursor = shift_month(cursor, -1)
    current = month_key(today())
    return st.selectbox(
        "ماه شمسی", months, index=months.index(current), format_func=month_label, key=key
    )


def transaction_form(store: Store, row: dict | None = None, *, prefix: str = "new") -> None:
    row = row or {}
    kind = st.segmented_control(
        "نوع تراکنش",
        list(KINDS),
        format_func=KINDS.__getitem__,
        default=row.get("kind", "expense"),
        key=f"{prefix}_kind",
        selection_mode="single",
        width="stretch",
        wrap=True,
    )
    kind = kind or "expense"
    categories = store.categories(kind)
    if row.get("category_id") and row.get("kind") == kind:
        existing = next(
            (c for c in store.categories(kind, active_only=False) if c["id"] == row["category_id"]),
            None,
        )
        if existing and existing not in categories:
            categories.append(existing)
    if not categories:
        st.info("ابتدا در تنظیمات یک دسته فعال برای این نوع تراکنش بسازید.")
        return
    ids = [c["id"] for c in categories]
    names = {c["id"]: c["name"] + (" (بایگانی)" if c["archived"] else "") for c in categories}
    with st.form(f"{prefix}_form", border=False):
        amount = st.text_input(
            "مبلغ (تومان)",
            value=str(row.get("amount", "")),
            placeholder="250,000",
            key=f"{prefix}_amount",
        )
        cols = st.columns(2)
        occurred = cols[0].text_input(
            "تاریخ شمسی",
            value=jalali(row.get("occurred_on", today())),
            help="قالب سال/ماه/روز؛ مانند 1405/08/09",
            key=f"{prefix}_date",
        )
        cid = cols[1].selectbox(
            "دسته",
            ids,
            index=ids.index(row["category_id"]) if row.get("category_id") in ids else 0,
            format_func=names.__getitem__,
            key=f"{prefix}_category",
        )
        note = st.text_input(
            "توضیح (اختیاری)",
            value=row.get("note", ""),
            max_chars=300,
            placeholder="مثلاً خرید هفتگی یا حقوق ماهانه",
            key=f"{prefix}_note",
        )
        if st.form_submit_button(
            "ذخیره تغییرات" if row else "ثبت تراکنش", type="primary", width="stretch"
        ):
            try:
                store.save_transaction(
                    parse_jalali(occurred), kind, amount_value(amount), cid, note, row.get("id")
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                notice("تغییرات تراکنش ذخیره شد." if row else "تراکنش ثبت شد.")


@st.dialog("ثبت تراکنش", width="small")
def add_transaction(store: Store) -> None:
    transaction_form(store)


@st.dialog("ویرایش تراکنش", width="small")
def edit_transaction(store: Store, row: dict) -> None:
    transaction_form(store, row, prefix=f"edit_{row['id']}")
    st.divider()
    confirmed = st.checkbox("حذف این تراکنش را تأیید می‌کنم.", key=f"confirm_{row['id']}")
    if st.button("حذف تراکنش", disabled=not confirmed, width="stretch"):
        try:
            store.delete_transaction(row["id"])
        except FinanceError as exc:
            st.error(str(exc))
        else:
            notice("تراکنش حذف شد.")


def ledger(rows: list[dict], *, limit: int | None = None) -> None:
    for row in rows[:limit] if limit else rows:
        sign = "+" if row["kind"] == "income" else "−"
        html(
            f'<div class="ledger-row"><div><div class="ledger-title">{escape(row["note"] or row["category"])}</div>'
            f'<div class="ledger-meta">{escape(row["category"])} · <bdi>{jalali(row["occurred_on"])}</bdi></div></div>'
            f'<div class="ledger-amount {row["kind"]}">{sign}{money(row["amount"])} <small>تومان</small></div></div>'
        )


def stat(label: str, value: int, css: str = "") -> None:
    icon = "↙" if css == "income" else "↗" if css == "expense" else "＝"
    html(
        f'<div class="stat"><div class="stat-top"><div class="stat-label">{label}</div>'
        f'<span class="stat-icon {css}" aria-hidden="true">{icon}</span></div>'
        f'<div class="stat-value {css}"><bdi>{money(value)}</bdi><span class="stat-unit">تومان</span></div></div>'
    )


def overview(store: Store) -> None:
    heading("یک نگاه به پول‌هایت", "درآمد، هزینه و پولی که برای آینده کنار گذاشته‌ای.")
    cols = st.columns([2, 1], vertical_alignment="bottom")
    with cols[0]:
        month = month_picker(store, "overview_month")
    with cols[1]:
        if st.button("ثبت تراکنش", icon=":material/add:", type="primary", width="stretch"):
            add_transaction(store)
    balances = store.balances()
    total, reserved, available = (balances[k] for k in ["total", "reserved", "available"])
    free_width = max(0, min(100, available / total * 100)) if total > 0 else 0
    html(
        f'<section class="balance-sheet"><div class="balance-title">کل موجودی · تا امروز</div>'
        f'<div class="balance-main"><span class="balance-number">{money(total)}</span><span class="balance-unit">تومان</span></div>'
        f'<div class="allocation" role="img" aria-label="قابل خرج {money(available)}؛ کنارگذاشته‌شده {money(reserved)} تومان">'
        f'<div class="free" style="width:{free_width:.2f}%"></div><div class="reserved" style="width:{100 - free_width:.2f}%"></div></div>'
        f'<div class="balance-legend"><div><span>قابل خرج</span><b>{money(available)} <small>تومان</small></b></div>'
        f'<div class="reserved-key"><span>کنارگذاشته‌شده برای هدف‌ها</span><b>{money(reserved)} <small>تومان</small></b></div></div></section>'
    )
    st.caption("موجودی بالا مربوط به تمام تراکنش‌هاست؛ آمار پایین فقط ماه انتخاب‌شده را نشان می‌دهد.")
    rows = store.transactions(month=month)
    income = sum(r["amount"] for r in rows if r["kind"] == "income")
    expense = sum(r["amount"] for r in rows if r["kind"] == "expense")
    for col, label, value, css in zip(
        st.columns(3),
        ["درآمد ماه", "هزینه ماه", "خالص ماه"],
        [income, expense, income - expense],
        ["income", "expense", ""],
        strict=True,
    ):
        with col:
            stat(label, value, css)
    left, right = st.columns([1.15, 1])
    with left, st.container(border=True):
        html('<div class="section-title">هزینه‌ها کجا رفته‌اند؟</div>')
        totals = {}
        for row in rows:
            if row["kind"] == "expense":
                totals[row["category"]] = totals.get(row["category"], 0) + row["amount"]
        if totals:
            ordered = sorted(totals.items(), key=lambda x: x[1])
            fig = go.Figure(
                go.Bar(
                    y=[escape(k) for k, _ in ordered],
                    x=[v for _, v in ordered],
                    orientation="h",
                    marker_color="#17654B",
                    marker_cornerradius=5,
                    text=[money(v) for _, v in ordered],
                    textposition="auto",
                    hovertemplate="%{y}<br>%{x:,.0f} تومان<extra></extra>",
                )
            )
            fig.update_layout(
                height=max(230, len(ordered) * 38),
                margin=dict(l=10, r=10, t=10, b=15),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(family="Vazirmatn, Tahoma", color="#18382E", size=12),
                xaxis=dict(
                    showgrid=True,
                    gridcolor="#E5E8DF",
                    zeroline=False,
                    title="تومان",
                    tickformat=",.0f",
                ),
                yaxis=dict(side="right"),
                showlegend=False,
            )
            st.plotly_chart(
                fig,
                width="stretch",
                alt="هزینه‌های ماه انتخاب‌شده به تفکیک دسته، به تومان",
                config={"displayModeBar": False, "locale": "en"},
            )
        else:
            empty(
                "هنوز هزینه‌ای در این ماه نیست", "با ثبت اولین هزینه، سهم هر دسته را اینجا ببینید."
            )
    with right, st.container(border=True):
        html('<div class="section-title">نبض بودجه‌های ماه</div>')
        budgets = [b for b in store.budgets(month) if b["limit"] is not None]
        if not budgets:
            empty("برای این ماه سقفی تعیین نشده", "از بخش بودجه‌ها برای دسته‌ها سقف هزینه بگذارید.")
        for budget in budgets[:5]:
            budget_progress(budget)
    with st.container(border=True):
        html('<div class="section-title">آخرین تراکنش‌های ماه</div>')
        if rows:
            ledger(rows, limit=5)
        else:
            empty(
                "دفتر این ماه هنوز خالی است",
                "از «ثبت تراکنش» برای واردکردن درآمد یا هزینه استفاده کنید.",
            )


def transactions_page(store: Store) -> None:
    heading("تراکنش‌ها", "درآمد و هزینه‌هایت را ثبت، پیدا و اصلاح کن.")
    if st.button("ثبت تراکنش", icon=":material/add:", type="primary"):
        add_transaction(store)
    with st.container(border=True, key="transaction_filters"):
        all_months = st.checkbox("همه ماه‌ها", value=False)
        cols = st.columns([1, 1, 1], vertical_alignment="bottom")
        with cols[0]:
            month = None if all_months else month_picker(store, "transactions_month")
        kind = cols[1].selectbox(
            "نوع", [None, "expense", "income"], format_func=lambda k: KINDS.get(k, "همه")
        )
        cats = store.categories(kind, active_only=False)
        names = {c["id"]: c["name"] for c in cats}
        cid = cols[2].selectbox(
            "دسته", [None, *names], format_func=lambda c: names.get(c, "همه دسته‌ها")
        )
        search = st.text_input(
            "جست‌وجو در توضیح، دسته یا مبلغ",
            placeholder="مثلاً خرید، خوراک یا 250000",
            type="search",
        )
    rows = store.transactions(month=month, kind=kind, category_id=cid, search=search)
    st.caption(
        f"{len(rows)} تراکنش · درآمد: {money(sum(r['amount'] for r in rows if r['kind'] == 'income'))} · هزینه: {money(sum(r['amount'] for r in rows if r['kind'] == 'expense'))} تومان"
    )
    if not rows:
        empty("تراکنشی پیدا نشد", "فیلترها را تغییر بده یا اولین تراکنش را ثبت کن.")
        return
    page_count = (len(rows) + 19) // 20
    page = st.selectbox("صفحه", list(range(1, page_count + 1))) if page_count > 1 else 1
    with st.container(border=True):
        for row in rows[(page - 1) * 20 : page * 20]:
            detail, action = st.columns([6, 1], vertical_alignment="center")
            with detail:
                ledger([row])
            with action:
                if st.button("ویرایش", key=f"edit_button_{row['id']}", width="stretch"):
                    edit_transaction(store, row)


def budget_progress(budget: dict) -> None:
    limit, spent = budget["limit"], budget["spent"]
    ratio = min(spent / limit, 1.0) if limit else (1.0 if spent else 0.0)
    over = spent > limit
    status = (
        f"{money(spent - limit)} تومان بیشتر از سقف"
        if over
        else f"{money(limit - spent)} تومان مانده"
    )
    percent = f"{spent / limit * 100:.0f}%" if limit else "سقف صفر"
    html(
        f'<div class="budget-item {"over-budget" if over else ""}">'
        f'<div class="budget-heading"><strong>{escape(budget["name"])}</strong><span class="budget-percent">{percent}</span></div>'
        f'<div class="budget-track" role="img" aria-label="{escape(status)}"><div style="width:{ratio * 100:.2f}%"></div></div>'
        f'<div class="budget-numbers"><span><bdi>{money(spent)}</bdi> از <bdi>{money(limit)}</bdi> تومان</span>'
        f'<span class="budget-status">{status}</span></div></div>'
    )


def budgets_page(store: Store) -> None:
    heading("بودجه‌ها", "برای هزینه‌های هر ماه حد بگذار؛ بدون انتقال مانده به ماه بعد.")
    month = month_picker(store, "budgets_month", future=True)
    st.caption(
        "قانون تکرارشونده از ماه انتخاب‌شده اعمال می‌شود؛ ماه‌های قبل تغییر نمی‌کنند. استثنای ماهانه بر قانون تکرارشونده اولویت دارد."
    )
    cats = store.categories("expense")
    if cats:
        with st.expander("تنظیم سقف هزینه", expanded=True), st.form("budget_form", border=False):
            names = {c["id"]: c["name"] for c in cats}
            columns = st.columns(2)
            cid = columns[0].selectbox("دسته هزینه", list(names), format_func=names.__getitem__)
            amount = columns[1].text_input("سقف (تومان)", placeholder="3,000,000")
            scope = st.segmented_control(
                "دامنه تغییر",
                ["از این ماه به بعد", "فقط همین ماه"],
                default="از این ماه به بعد",
                width="stretch",
                wrap=True,
            )
            st.caption(
                "سقف صفر یعنی هیچ هزینه‌ای مجاز نیست؛ برای توقف بودجه تکرارشونده می‌توان سقف صفر گذاشت."
            )
            if st.form_submit_button("ذخیره بودجه", type="primary"):
                try:
                    store.save_budget(
                        cid,
                        month,
                        amount_value(amount, allow_zero=True),
                        ongoing=scope != "فقط همین ماه",
                    )
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    notice("بودجه ذخیره شد.")
    budgets = store.budgets(month)
    configured = [b for b in budgets if b["limit"] is not None]
    if not configured:
        empty("هنوز بودجه‌ای تنظیم نشده", "برای یکی از دسته‌های هزینه، سقف ماهانه ثبت کن.")
    budget_columns = st.columns(2)
    for index, budget in enumerate(configured):
        with budget_columns[index % 2], st.container(border=True):
            budget_progress(budget)
            if budget["override"]:
                st.caption("استثنای همین ماه")
                if st.button("حذف استثنا و بازگشت به قانون", key=f"remove_override_{index}"):
                    store.remove_override(budget["id"], month)
                    notice("استثنای ماهانه حذف شد.")
    unbudgeted = [b for b in budgets if b["limit"] is None and b["spent"]]
    if unbudgeted:
        st.info(
            "هزینه‌های بدون سقف: "
            + "، ".join(f"{b['name']} ({money(b['spent'])} تومان)" for b in unbudgeted)
        )


def goal_form(store: Store, goal: dict | None = None) -> None:
    goal = goal or {}
    with st.form(f"goal_form_{goal.get('id', 'new')}", border=False):
        name = st.text_input(
            "نام هدف", value=goal.get("name", ""), max_chars=80, placeholder="مثلاً لپ‌تاپ جدید"
        )
        target = st.text_input(
            "مبلغ هدف (تومان)", value=str(goal.get("target", "")), placeholder="45,000,000"
        )
        deadline = st.text_input(
            "تاریخ مهلت شمسی (اختیاری)",
            value=jalali(goal["deadline"]) if goal.get("deadline") else "",
            placeholder="1406/01/01",
        )
        if st.form_submit_button("ذخیره هدف" if goal else "ساخت هدف", type="primary"):
            try:
                store.save_goal(
                    name,
                    amount_value(target),
                    parse_jalali(deadline) if deadline.strip() else None,
                    goal.get("id"),
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                notice("هدف ذخیره شد.")


def goals_page(store: Store) -> None:
    heading("هدف‌ها", "برای چیزهای مهم پول کنار بگذار؛ بدون ثبت هزینه ساختگی.")
    balances = store.balances()
    html(
        '<div class="goal-summary"><div><span class="eyebrow">آینده را قدم‌به‌قدم بساز</span>'
        "<p>کنارگذاشتن پول، موجودی کل را تغییر نمی‌دهد.</p></div>"
        f"<div><span>آماده برای تخصیص</span><strong><bdi>{money(max(0, balances['available']))}</bdi> <small>تومان</small></strong></div></div>"
    )
    with st.expander("＋ هدف تازه"):
        goal_form(store)
    goals = store.goals()
    active = [g for g in goals if g["status"] == "active"]
    if not active:
        empty("هدفی در حال انجام نیست", "یک هدف تازه بساز و بخشی از موجودی را برای آن کنار بگذار.")
    for goal in active:
        gid = goal["id"]
        with st.container(border=True):
            html(
                f'<div class="goal-heading"><div class="goal-symbol" aria-hidden="true">◎</div>'
                f'<strong>{escape(goal["name"])}</strong><span class="pill">در حال انجام</span></div>'
                f'<div class="goal-amount"><bdi>{money(goal["reserved"])}</bdi><span>از {money(goal["target"])} تومان</span></div>'
            )
            st.progress(min(goal["reserved"] / goal["target"], 1.0))
            st.caption(
                f"{money(goal['reserved'])} از {money(goal['target'])} تومان · {goal['reserved'] / goal['target']:.0%}"
            )
            if goal["deadline"]:
                days = (date.fromisoformat(goal["deadline"]) - today()).days
                st.caption(
                    f"مهلت: {jalali(goal['deadline'])} · "
                    + (f"{days} روز باقی‌مانده" if days >= 0 else "مهلت گذشته است")
                )
            with st.form(f"goal_money_{gid}", border=False):
                cols = st.columns([1, 2])
                operation = cols[0].selectbox("عملیات", ["کنارگذاشتن", "آزادسازی"])
                amount = cols[1].text_input("مبلغ (تومان)", key=f"goal_amount_{gid}")
                if st.form_submit_button("ثبت تخصیص / آزادسازی"):
                    try:
                        store.move_goal_money(
                            gid, amount_value(amount), release=operation == "آزادسازی"
                        )
                    except FinanceError as exc:
                        st.error(str(exc))
                    else:
                        notice("پول هدف به‌روز شد.")
            with st.expander("ویرایش، تاریخچه و پایان هدف"):
                goal_form(store, goal)
                for entry in store.goal_history(gid):
                    st.caption(
                        f"{jalali(entry['created_on'])} · {'کنارگذاشتن' if entry['amount'] > 0 else 'آزادسازی'} · {money(abs(entry['amount']))} تومان"
                    )
                st.caption(
                    "قبل از پایان هدف، تمام پولش را آزاد کن. خرید واقعی را جداگانه به‌عنوان هزینه ثبت کن."
                )
                status = st.selectbox(
                    "پایان هدف", ["تکمیل‌شده", "بایگانی‌شده"], key=f"goal_status_{gid}"
                )
                confirmed = st.checkbox(
                    "پایان این هدف را تأیید می‌کنم.", key=f"goal_close_confirm_{gid}"
                )
                if st.button(
                    "پایان هدف",
                    key=f"goal_close_{gid}",
                    disabled=not confirmed or goal["reserved"] != 0,
                ):
                    try:
                        store.close_goal(gid, completed=status == "تکمیل‌شده")
                    except FinanceError as exc:
                        st.error(str(exc))
                    else:
                        notice("هدف به تاریخچه منتقل شد.")
    closed = [g for g in goals if g["status"] != "active"]
    if closed:
        with st.expander("هدف‌های پایان‌یافته"):
            for goal in closed:
                st.write(
                    f"{goal['name']} — {'تکمیل‌شده' if goal['status'] == 'completed' else 'بایگانی‌شده'} · {money(goal['target'])} تومان"
                )
                for entry in store.goal_history(goal["id"]):
                    st.caption(f"{jalali(entry['created_on'])} · {money(entry['amount'])} تومان")


def settings_page(store: Store, demo: bool) -> None:
    heading("تنظیمات", "دسته‌ها، نسخه پشتیبان و اطلاعات شروع حساب.")
    setting = store.settings()
    if not setting:
        return
    with st.container(border=True):
        st.subheader("اطلاعات حساب")
        st.write(
            f"شروع: {jalali(setting['opening_date'])} · موجودی اولیه: {money(setting['opening_balance'])} تومان"
        )
        st.caption(
            "موجودی اولیه درآمد نیست و در گزارش ماهانه حساب نمی‌شود. برای حفظ تاریخچه، افتتاحیه پس از ثبت قابل تغییر نیست."
        )
        st.caption(f"فایل فعال: {store.path.name} · {'داده نمایشی' if demo else 'داده شخصی'}")
    with st.container(border=True):
        st.subheader("خروجی و پشتیبان")
        st.caption(
            "CSV شامل همه تراکنش‌هاست. پشتیبان SQLite شامل تراکنش‌ها، بودجه‌ها، هدف‌ها، دسته‌ها و تنظیمات است؛ رمزگذاری نشده است."
        )
        col1, col2 = st.columns(2)
        label = "demo" if demo else "personal"
        stamp = today().isoformat()
        with col1:
            st.download_button(
                "دریافت CSV تراکنش‌ها",
                store.export_csv(),
                f"hesab-{label}-{stamp}.csv",
                "text/csv",
                width="stretch",
            )
        with col2:
            st.download_button(
                "دریافت پشتیبان کامل",
                store.backup(),
                f"hesab-{label}-{stamp}.sqlite3",
                "application/vnd.sqlite3",
                width="stretch",
            )
        st.caption(
            "بازیابی از داخل رابط وجود ندارد. روش بازیابی دستی و امن در README نوشته شده است."
        )
    st.subheader("دسته‌ها")
    with st.expander("ساخت دسته تازه"):
        with st.form("new_category"):
            name = st.text_input("نام دسته تازه", max_chars=80)
            kind = st.selectbox("نوع دسته تازه", list(KINDS), format_func=KINDS.__getitem__)
            if st.form_submit_button("ساخت دسته"):
                try:
                    store.save_category(name, kind)
                except FinanceError as exc:
                    st.error(str(exc))
                else:
                    notice("دسته ساخته شد.")
    cats = store.categories(active_only=False)
    names = {
        c["id"]: f"{c['name']} · {KINDS[c['kind']]}" + (" · بایگانی" if c["archived"] else "")
        for c in cats
    }
    cid = st.selectbox("دسته برای ویرایش", list(names), format_func=names.__getitem__)
    selected = next(c for c in cats if c["id"] == cid)
    with st.form(f"category_edit_{cid}"):
        name = st.text_input("نام دسته", value=selected["name"], max_chars=80)
        archived = st.checkbox("بایگانی (پنهان از ثبت‌های جدید)", value=bool(selected["archived"]))
        if st.form_submit_button("ذخیره دسته"):
            try:
                store.save_category(name, selected["kind"], cid)
                store.archive_category(cid, archived)
            except FinanceError as exc:
                st.error(str(exc))
            else:
                notice("دسته به‌روز شد؛ تاریخچه حفظ شده است.")


def onboarding(store: Store) -> None:
    heading("به حساب خوش آمدی", "یک نقطه شروع مشخص کن؛ بعد درآمد و هزینه‌ها را ثبت کن.")
    with st.container(border=True):
        st.subheader("پول تو در روز شروع")
        st.write(
            "مجموع پول نقد و حساب‌های بانکی‌ات را در یک موجودی وارد کن. تراکنش‌های قبل از این تاریخ وارد حساب نمی‌شوند."
        )
        with st.form("opening"):
            opening = st.text_input("تاریخ شروع شمسی", value=jalali(today()))
            balance = st.text_input("مبلغ موجودی اولیه (تومان)", placeholder="0")
            st.caption("برای واردکردن تراکنش‌های قدیمی، تاریخ شروع و موجودی همان روز را انتخاب کن.")
            if st.form_submit_button("شروع حساب", type="primary"):
                try:
                    store.setup(parse_jalali(opening), amount_value(balance, allow_zero=True))
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    notice("حساب آماده است؛ اولین تراکنش را ثبت کن.")
    st.info("برای دیدن یک حساب آماده با داده‌های ساختگی، «حالت نمایشی» را از نوار کناری روشن کن.")


def main() -> None:
    st.set_page_config(
        page_title="حساب | مدیریت مالی شخصی",
        page_icon="🌿",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    html(f"<style>{(ROOT / 'static/style.css').read_text()}</style>")
    with st.sidebar:
        html(
            '<div class="brand"><div class="brand-mark">ح</div><div><div class="brand-name">حساب</div><div class="brand-note">پول‌هایت، روشن و مرتب.</div></div></div>'
        )
        html(
            '<div class="sidebar-date"><span>دفتر شخصی</span>'
            f"<span>امروز · <bdi>{jalali(today())}</bdi></span></div>"
        )
        st.caption("مدیریت مالی")
        page = st.radio(
            "بخش‌های حساب",
            PAGES,
            label_visibility="collapsed",
            key="main_navigation",
            format_func=lambda name: f":material/{PAGE_ICONS[name]}: {name}",
            width="stretch",
        )
        with st.container(key="sidebar_footer"):
            with st.container(border=True, key="sidebar_mode"):
                demo = st.toggle(
                    "حالت نمایشی",
                    value=False,
                    help="داده‌های ساختگی و جدا از حساب شخصی؛ تغییرات این حالت روی اطلاعات شخصی اثری ندارد.",
                )
                st.caption(
                    "داده‌های آزمایشی؛ جدا از حساب شما"
                    if demo
                    else "برای آشنایی، با داده‌های آزمایشی کار کن."
                )
            st.markdown(":material/lock: محلی و خصوصی")
            st.caption("فقط روی دستگاه شما · مبالغ به تومان")
    mode = "demo" if demo else "personal"
    if st.session_state.get("active_mode") != mode:
        # Do not leak draft transaction/goal values across personal and demo modes.
        for key in list(st.session_state):
            if key.startswith(("new_", "edit_", "goal_", "confirm_")):
                del st.session_state[key]
        st.session_state["active_mode"] = mode
    data_dir = Path(os.environ.get("HESAB_DATA_DIR", str(ROOT / "data")))
    store = Store(data_dir / f"{mode}.sqlite3")
    if demo:
        seed_demo(store)
        st.warning("حالت نمایشی · این اطلاعات ساختگی است و از حساب شخصی شما جداست.")
    if message := st.session_state.pop("notice", None):
        st.success(message)
    if not store.settings():
        onboarding(store)
        return
    balances = store.balances()
    if balances["total"] < 0:
        st.error(
            f"موجودی کل {money(abs(balances['total']))} تومان منفی است. تراکنش‌ها و موجودی ثبت‌شده را بررسی کن."
        )
    if balances["available"] < 0 and balances["reserved"] > 0:
        st.warning(
            f"پول قابل خرج {money(abs(balances['available']))} تومان کسری دارد. برای پوشش ذخیره هدف‌ها، پول آزاد کن یا درآمد واقعی ثبت کن. ذخیره‌ها خودکار تغییر نکرده‌اند."
        )
    {
        "نمای کلی": overview,
        "تراکنش‌ها": transactions_page,
        "بودجه‌ها": budgets_page,
        "هدف‌ها": goals_page,
        "تنظیمات": lambda s: settings_page(s, demo),
    }[page](store)
