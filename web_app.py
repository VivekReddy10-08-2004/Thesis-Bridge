"""Flask web application for authenticated report generation and retrieval.

This app provides:
- email/password auth
- per-user report history and exports
- mode-specific research/analysis pipeline execution
- usage limiting for non-admin users
"""

import json
import os
import csv
import io
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, flash, g, redirect, render_template, request, send_from_directory, session, url_for, Response
import psycopg
from psycopg.rows import dict_row
from werkzeug.security import check_password_hash, generate_password_hash

from analyst_agent import AnalystAgent
from main import build_markdown_report
from search_agent import SearchAgent


BASE_DIR = Path(__file__).resolve().parent
REPORTS_DIR = BASE_DIR / "reports"

load_dotenv()


app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET_KEY", "change-me-in-prod")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required. Set it to your Supabase Postgres connection string.")


ADMIN_UNLIMITED_USER_ID = 1
FREE_USER_LLM_LIMIT = 2

# Track if DB has been initialized
_db_initialized = False

MODE_OPTIONS = {
    "public_markets": "Public Markets (Wealth Management)",
    "private_equity": "Private Equity (Value Creation)",
}


def normalize_mode(value):
    """Normalize mode values and fall back to private_equity if invalid."""
    value = (value or "").strip().lower()
    return value if value in MODE_OPTIONS else "private_equity"


def get_db():
    """Get a request-scoped Postgres connection."""
    if "db" not in g:
        g.db = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    return g.db


@app.teardown_appcontext
def close_db(error):
    """Close request-scoped database connection after each request."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.before_request
def ensure_db_initialized():
    """If DB init failed at startup, retry on first request."""
    global _db_initialized
    if not _db_initialized:
        try:
            init_db()
            _db_initialized = True
            print("DB initialized successfully on first request")
        except Exception as e:
            print(f" DB init still failing: {e}")
            # Let the route handle it (some routes don't need DB)


def init_db():
    """Create required tables and run lightweight schema upgrades."""
    REPORTS_DIR.mkdir(exist_ok=True)
    db = psycopg.connect(DATABASE_URL)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id BIGSERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS reports (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'private_equity',
            thesis TEXT NOT NULL,
            baseline_revenue INTEGER NOT NULL,
            confidence_score INTEGER NOT NULL,
            markdown_path TEXT NOT NULL,
            raw_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_usage (
            user_id BIGINT PRIMARY KEY,
            total_calls INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )

    columns = {
        row[0]
        for row in db.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'reports'
            """
        ).fetchall()
    }
    if "mode" not in columns:
        db.execute("ALTER TABLE reports ADD COLUMN mode TEXT")
        db.execute("UPDATE reports SET mode = 'private_equity' WHERE mode IS NULL OR mode = ''")

    db.commit()
    db.close()


# Try to initialize DB at startup, but don't crash if connection fails
try:
    init_db()
    _db_initialized = True
except Exception as e:
    print(f"DB init failed at startup (will retry on first request): {e}")
    _db_initialized = False


def current_user():
    """Return the logged-in user row from session, or None if anonymous."""
    user_id = session.get("user_id")
    if not user_id:
        return None
    db = get_db()
    return db.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()


def login_required():
    """Redirect anonymous users to the auth screen."""
    if not current_user():
        return redirect(url_for("auth"))
    return None


def save_markdown_for_user(user_id, thesis, report):
    """Save one generated report as markdown and return the file name."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_user = f"user_{user_id}"
    output_name = f"memo_{safe_user}_{timestamp}.md"
    output_path = REPORTS_DIR / output_name
    output_path.write_text(build_markdown_report(thesis, report), encoding="utf-8")
    return output_name


def get_llm_usage_count(user_id):
    """Fetch total successful LLM-backed analyses for a user."""
    db = get_db()
    row = db.execute(
        "SELECT total_calls FROM llm_usage WHERE user_id = %s",
        (user_id,),
    ).fetchone()
    if not row:
        return 0
    return int(row["total_calls"] or 0)


def increment_llm_usage_count(user_id):
    """Increment successful LLM usage counter for a user."""
    db = get_db()
    updated_at = datetime.utcnow().isoformat()
    db.execute(
        """
        INSERT INTO llm_usage (user_id, total_calls, updated_at)
        VALUES (%s, 1, %s)
        ON CONFLICT(user_id) DO UPDATE SET
            total_calls = total_calls + 1,
            updated_at = excluded.updated_at
        """,
        (user_id, updated_at),
    )
    db.commit()


def run_live_pipeline(mode, thesis, baseline_revenue):
    """Execute search + analysis for a selected mode and return report JSON."""
    searcher = SearchAgent()
    analyst = AnalystAgent()

    if mode == "public_markets":
        search_results = searcher.process_search_public(thesis)
        report = analyst.analyze_public_markets(
            search_results,
            thesis=thesis,
            baseline_revenue=baseline_revenue,
        )
    elif mode == "private_equity":
        search_results = searcher.process_search_private(thesis)
        report = analyst.analyze_private_equity(
            search_results,
            thesis=thesis,
            baseline_revenue=baseline_revenue,
        )
    else:
        raise RuntimeError(f"Unsupported mode: {mode}")

    if not search_results or isinstance(search_results, str):
        raise RuntimeError("Search failed or returned no results.")
    if "error" in report:
        raise RuntimeError(report["error"])

    return report


def build_excel_rows(report):
    """Flatten nested evidence metrics into tabular rows for CSV export."""
    mode = normalize_mode(report.get("mode"))
    rows = []
    for item in report.get("ranked_evidence", []):
        metrics = item.get("extracted_metrics", [])
        if not metrics:
            base_row = {
                "score": item.get("score", 0),
                "evidence_strength": item.get("evidence_strength", "medium"),
                "weakness_note": item.get("weakness_note", ""),
                "title": item.get("title", ""),
                "source": item.get("source", ""),
                "why_it_matters": item.get("why_it_matters", ""),
                "metric": "",
                "unit": "",
                "timeframe": "",
                "impact_direction": "",
                "metric_source_url": item.get("source", ""),
                "citation_locator": "",
                "metric_confidence": "",
                "source_excerpt": "",
                "caveat": "",
            }
            if mode == "public_markets":
                base_row.update(
                    {
                        "ticker": "",
                        "previous_period": "",
                        "current_period": "",
                        "delta": "",
                    }
                )
            else:
                base_row.update(
                    {
                        "before_value": "",
                        "after_value": "",
                        "impact": "",
                    }
                )
            rows.append(base_row)
            continue

        for metric in metrics:
            base_row = {
                "score": item.get("score", 0),
                "evidence_strength": item.get("evidence_strength", "medium"),
                "weakness_note": item.get("weakness_note", ""),
                "title": item.get("title", ""),
                "source": item.get("source", ""),
                "why_it_matters": item.get("why_it_matters", ""),
                "metric": metric.get("metric", ""),
                "unit": metric.get("unit", ""),
                "timeframe": metric.get("timeframe", ""),
                "impact_direction": metric.get("impact_direction", ""),
                "metric_source_url": metric.get("metric_source_url", item.get("source", "")),
                "citation_locator": metric.get("citation_locator", ""),
                "metric_confidence": metric.get("confidence", ""),
                "source_excerpt": metric.get("source_excerpt", ""),
                "caveat": metric.get("caveat", ""),
            }
            if mode == "public_markets":
                base_row.update(
                    {
                        "ticker": metric.get("ticker", ""),
                        "previous_period": metric.get("previous_period", ""),
                        "current_period": metric.get("current_period", ""),
                        "delta": metric.get("delta", ""),
                    }
                )
            else:
                base_row.update(
                    {
                        "before_value": metric.get("before_value", ""),
                        "after_value": metric.get("after_value", ""),
                        "impact": metric.get("impact", ""),
                    }
                )
            rows.append(base_row)
    return rows


def get_table_columns(mode):
    """Return export table columns based on report mode."""
    mode = normalize_mode(mode)
    shared = [
        ("score", "Score"),
        ("evidence_strength", "Strength"),
        ("title", "Title"),
        ("metric", "Metric"),
    ]
    if mode == "public_markets":
        mode_cols = [
            ("ticker", "Ticker"),
            ("previous_period", "Previous Period"),
            ("current_period", "Current Period"),
            ("delta", "Delta"),
        ]
    else:
        mode_cols = [
            ("before_value", "Before"),
            ("after_value", "After"),
            ("impact", "Impact"),
        ]

    tail = [
        ("unit", "Unit"),
        ("timeframe", "Timeframe"),
        ("impact_direction", "Direction"),
        ("metric_confidence", "Confidence"),
        ("metric_source_url", "Metric Source"),
        ("citation_locator", "Citation Locator"),
        ("source_excerpt", "Source Excerpt"),
        ("caveat", "Caveat"),
    ]
    return shared + mode_cols + tail


def build_quality_gate_summary(report):
    """Compute simple source/metric coverage checks for the report page."""
    ranked = report.get("ranked_evidence", [])
    source_count = len(ranked)
    metric_count = sum(len(item.get("extracted_metrics", [])) for item in ranked)
    weak_sources = [
        item for item in ranked
        if str(item.get("evidence_strength", "")).lower() == "weak"
    ]

    return {
        "source_count": source_count,
        "metric_count": metric_count,
        "weak_source_count": len(weak_sources),
        "source_gate_pass": source_count >= 3,
        "metric_gate_pass": metric_count >= 5,
        "weak_sources": weak_sources,
    }


@app.route("/", methods=["GET"])
def home():
    """Route users to dashboard if logged in, else auth page."""
    if current_user():
        return redirect(url_for("dashboard"))
    return redirect(url_for("auth"))


@app.route("/auth", methods=["GET", "POST"])
def auth():
    """Handle login and signup with session-based authentication."""
    if request.method == "GET":
        return render_template("auth.html")

    action = request.form.get("action", "login")
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not email or not password:
        flash("Email and password are required.", "error")
        return redirect(url_for("auth"))

    db = get_db()

    if action == "signup":
        existing = db.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone()
        if existing:
            flash("Account already exists. Please login.", "error")
            return redirect(url_for("auth"))

        password_hash = generate_password_hash(password)
        created_at = datetime.utcnow().isoformat()
        user = db.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (%s, %s, %s) RETURNING id",
            (email, password_hash, created_at),
        ).fetchone()
        db.commit()
        session["user_id"] = user["id"]
        flash("Welcome. Your account is ready.", "success")
        return redirect(url_for("dashboard"))

    user = db.execute("SELECT * FROM users WHERE email = %s", (email,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        flash("Invalid credentials.", "error")
        return redirect(url_for("auth"))

    session["user_id"] = user["id"]
    flash("Logged in successfully.", "success")
    return redirect(url_for("dashboard"))


@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    """Show report history and handle new analysis job submissions."""
    gate = login_required()
    if gate:
        return gate

    user = current_user()
    db = get_db()

    if request.method == "POST":
        mode = normalize_mode(request.form.get("mode"))
        thesis = request.form.get("thesis", "").strip()
        baseline = request.form.get("baseline_revenue", "1000000").strip()

        if not thesis:
            flash("Please enter a thesis before running analysis.", "error")
            return redirect(url_for("dashboard"))

        try:
            baseline_revenue = int(baseline)
            if baseline_revenue <= 0:
                raise ValueError("Baseline must be positive")
        except ValueError:
            flash("Baseline revenue must be a positive integer.", "error")
            return redirect(url_for("dashboard"))

        if user["id"] != ADMIN_UNLIMITED_USER_ID:
            # Non-admin users are limited to a small number of successful runs.
            current_usage = get_llm_usage_count(user["id"])
            if current_usage >= FREE_USER_LLM_LIMIT:
                flash(
                    f"Usage limit reached. Non-admin users can run analysis only {FREE_USER_LLM_LIMIT} times.",
                    "error",
                )
                return redirect(url_for("dashboard"))

        try:
            report = run_live_pipeline(mode, thesis, baseline_revenue)
            markdown_name = save_markdown_for_user(user["id"], thesis, report)
            created_at = datetime.utcnow().isoformat()
            confidence = int(report.get("confidence_score", 0))
            inserted = db.execute(
                """
                INSERT INTO reports (user_id, mode, thesis, baseline_revenue, confidence_score, markdown_path, raw_json, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    user["id"],
                    mode,
                    thesis,
                    baseline_revenue,
                    confidence,
                    markdown_name,
                    json.dumps(report),
                    created_at,
                ),
            ).fetchone()
            db.commit()

            if user["id"] != ADMIN_UNLIMITED_USER_ID:
                # Count only successful completed analyses.
                increment_llm_usage_count(user["id"])

            flash("Memo generated successfully.", "success")
            return redirect(url_for("view_report", report_id=inserted["id"]))
        except Exception as exc:
            flash(f"Analysis failed: {exc}", "error")
            return redirect(url_for("dashboard"))

    reports = db.execute(
        """
        SELECT id, mode, thesis, confidence_score, created_at
        FROM reports
        WHERE user_id = %s
        ORDER BY id DESC
        LIMIT 8
        """,
        (user["id"],),
    ).fetchall()

    return render_template("dashboard.html", user=user, reports=reports, mode_options=MODE_OPTIONS)


@app.route("/insights")
def insights():
    """Render aggregate stats derived from the current user's report history."""
    gate = login_required()
    if gate:
        return gate

    user = current_user()
    db = get_db()

    totals = db.execute(
        """
        SELECT
            COUNT(*) AS report_count,
            COALESCE(AVG(confidence_score), 0) AS avg_confidence,
            COALESCE(MAX(confidence_score), 0) AS max_confidence,
            COALESCE(MIN(confidence_score), 0) AS min_confidence
        FROM reports
        WHERE user_id = %s
        """,
        (user["id"],),
    ).fetchone()

    mode_rows = db.execute(
        """
        SELECT mode, COUNT(*) AS count
        FROM reports
        WHERE user_id = %s
        GROUP BY mode
        ORDER BY count DESC
        """,
        (user["id"],),
    ).fetchall()

    confidence_rows = db.execute(
        """
        SELECT confidence_score, COUNT(*) AS count
        FROM reports
        WHERE user_id = %s
        GROUP BY confidence_score
        ORDER BY confidence_score ASC
        """,
        (user["id"],),
    ).fetchall()

    top_theses = db.execute(
        """
        SELECT thesis, COUNT(*) AS run_count, ROUND(AVG(confidence_score), 2) AS avg_confidence
        FROM reports
        WHERE user_id = %s
        GROUP BY thesis
        ORDER BY run_count DESC, avg_confidence DESC
        LIMIT 8
        """,
        (user["id"],),
    ).fetchall()

    latest_reports = db.execute(
        """
        SELECT id, thesis, mode, confidence_score, created_at
        FROM reports
        WHERE user_id = %s
        ORDER BY id DESC
        LIMIT 12
        """,
        (user["id"],),
    ).fetchall()

    max_mode_count = max([row["count"] for row in mode_rows], default=1)
    mode_breakdown = [
        {
            "mode": row["mode"],
            "mode_label": MODE_OPTIONS.get(row["mode"], row["mode"]),
            "count": row["count"],
            "width_pct": int((row["count"] / max_mode_count) * 100) if max_mode_count else 0,
        }
        for row in mode_rows
    ]

    max_conf_count = max([row["count"] for row in confidence_rows], default=1)
    confidence_distribution = [
        {
            "score": row["confidence_score"],
            "count": row["count"],
            "width_pct": int((row["count"] / max_conf_count) * 100) if max_conf_count else 0,
        }
        for row in confidence_rows
    ]

    return render_template(
        "insights.html",
        user=user,
        mode_options=MODE_OPTIONS,
        report_count=totals["report_count"],
        avg_confidence=round(float(totals["avg_confidence"] or 0), 2),
        max_confidence=int(totals["max_confidence"] or 0),
        min_confidence=int(totals["min_confidence"] or 0),
        mode_breakdown=mode_breakdown,
        confidence_distribution=confidence_distribution,
        top_theses=top_theses,
        latest_reports=latest_reports,
    )


@app.route("/reports/<int:report_id>")
def view_report(report_id):
    """Render one saved report owned by the current user."""
    gate = login_required()
    if gate:
        return gate

    user = current_user()
    db = get_db()
    row = db.execute(
        "SELECT * FROM reports WHERE id = %s AND user_id = %s",
        (report_id, user["id"]),
    ).fetchone()

    if not row:
        flash("Report not found.", "error")
        return redirect(url_for("dashboard"))

    report_json = json.loads(row["raw_json"])
    mode = normalize_mode(row["mode"] or report_json.get("mode"))
    report_json["mode"] = mode
    excel_rows = build_excel_rows(report_json)
    qa = build_quality_gate_summary(report_json)
    table_columns = get_table_columns(mode)

    return render_template(
        "report.html",
        report_id=row["id"],
        mode=mode,
        mode_label=MODE_OPTIONS.get(mode, mode),
        thesis=row["thesis"],
        baseline_revenue=row["baseline_revenue"],
        confidence=row["confidence_score"],
        created_at=row["created_at"],
        report=report_json,
        excel_rows=excel_rows,
        table_columns=table_columns,
        qa=qa,
    )


@app.route("/reports/<int:report_id>/download")
def download_report_markdown(report_id):
    """Download markdown memo file for a report owned by current user."""
    gate = login_required()
    if gate:
        return gate

    user = current_user()
    db = get_db()
    row = db.execute(
        "SELECT markdown_path FROM reports WHERE id = %s AND user_id = %s",
        (report_id, user["id"]),
    ).fetchone()

    if not row:
        flash("Report file not found.", "error")
        return redirect(url_for("dashboard"))

    return send_from_directory(REPORTS_DIR, row["markdown_path"], as_attachment=True)


@app.route("/reports/<int:report_id>/download-csv")
def download_report_csv(report_id):
    """Download a CSV extract of report evidence and metrics."""
    gate = login_required()
    if gate:
        return gate

    user = current_user()
    db = get_db()
    row = db.execute(
        "SELECT mode, thesis, raw_json FROM reports WHERE id = %s AND user_id = %s",
        (report_id, user["id"]),
    ).fetchone()

    if not row:
        flash("Report data not found.", "error")
        return redirect(url_for("dashboard"))

    report_json = json.loads(row["raw_json"])
    mode = normalize_mode(row["mode"] or report_json.get("mode"))
    report_json["mode"] = mode
    fieldnames = [name for name, _ in get_table_columns(mode)]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for item in build_excel_rows(report_json):
        writer.writerow(item)

    csv_text = output.getvalue()
    output.close()

    safe_name = "report_data.csv"
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={safe_name}"},
    )


@app.route("/logout")
def logout():
    """Clear session and return user to auth screen."""
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("auth"))


if __name__ == "__main__":
    init_db()
    # Use a production WSGI server for deployment; debug mode is local-only.
    app.run(debug=True)
