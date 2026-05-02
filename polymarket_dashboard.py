#!/usr/bin/env python3
"""
Streamlit dashboard for Polymarket trading bot.
Reads trading journal (~/trading/trading-log.yaml) and open positions (~/.polymarket_bot/positions.json).
"""

import yaml
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import streamlit as st

# ─── Paths ─────────────────────────────────────────────────────────────────────
JOURNAL_PATH = Path.home() / "trading/trading-log.yaml"
POSITIONS_PATH = Path.home() / ".polymarket_bot/positions.json"

# ─── Data loading ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=10)  # refresh every 10s while running
def load_journal() -> pd.DataFrame:
    """Load all historical trades from the multi-doc YAML journal."""
    if not JOURNAL_PATH.exists():
        return pd.DataFrame()

    text = JOURNAL_PATH.read_text()
    # Split on YAML document separator (--- on its own line)
    docs = []
    for doc in text.split("\n---\n"):
        doc = doc.strip()
        if doc:
            try:
                entry = yaml.safe_load(doc)
                if isinstance(entry, dict):
                    docs.append(entry)
            except yaml.YAMLError:
                continue

    df = pd.DataFrame(docs)

    # Normalise columns
    if df.empty:
        return df

    # Parse dates
    for date_col in ["date", "exit_date"]:
        if date_col in df.columns:
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce", utc=True)

    # Numeric cleanup
    for num_col in ["entry_price", "exit_price", "size_usdc", "size_pct",
                     "pnl_usdc", "pnl_pct", "confidence"]:
        if num_col in df.columns:
            df[num_col] = pd.to_numeric(df[num_col], errors="coerce")

    # Hold time (seconds) if both dates exist
    if "date" in df.columns and "exit_date" in df.columns:
        df["hold_seconds"] = (df["exit_date"] - df["date"]).dt.total_seconds()

    return df.sort_values("date", ascending=False).reset_index(drop=True)


@st.cache_data(ttl=10)
def load_positions() -> dict:
    """Load currently open positions (if bot is running)."""
    if not POSITIONS_PATH.exists():
        return {}
    try:
        return json.loads(POSITIONS_PATH.read_text())
    except Exception:
        return {}


def compute_equity_curve(trades: pd.DataFrame) -> pd.DataFrame:
    """Build running equity curve from closed trades."""
    if trades.empty or "pnl_usdc" not in trades.columns:
        return pd.DataFrame()

    closed = trades.dropna(subset=["pnl_usdc"]).sort_values("date")
    if closed.empty:
        return pd.DataFrame()

    closed["cum_pnl"] = closed["pnl_usdc"].cumsum()
    return closed[["date", "cum_pnl", "market", "outcome"]]


# ─── Streamlit UI ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Polymarket Trading Dashboard", layout="wide")

st.title("📊 Polymarket Trading Dashboard")

tab1, tab2, tab3 = st.tabs(["Overview", "Closed Trades", "Open Positions"])

# ── Tab 1: Overview ────────────────────────────────────────────────────────────
with tab1:
    trades = load_journal()
    positions = load_positions()

    col1, col2, col3, col4 = st.columns(4)

    if trades.empty:
        col1.metric("Total P&L", "$0.00")
        col2.metric("Win Rate", "—")
        col3.metric("Total Trades", "0")
        col4.metric("Avg Hold Time", "—")
        st.info("No closed trades logged yet. Run the bot to populate the journal.")
    else:
        closed = trades.dropna(subset=["pnl_usdc"])
        total_pnl = closed["pnl_usdc"].sum()
        wins = closed[closed["outcome"] == "win"]
        win_rate = len(wins) / len(closed) * 100 if len(closed) > 0 else 0
        avg_hold_sec = closed["hold_seconds"].mean() if "hold_seconds" in closed.columns else None

        col1.metric("Total P&L", f"${total_pnl:,.2f}")
        col2.metric("Win Rate", f"{win_rate:.1f}%")
        col3.metric("Total Trades", f"{len(closed)}")
        if avg_hold_sec:
            if avg_hold_sec > 3600:
                col4.metric("Avg Hold Time", f"{avg_hold_sec/3600:.1f}h")
            else:
                col4.metric("Avg Hold Time", f"{avg_hold_sec/60:.0f}m")

        # Equity curve
        st.subheader("Equity Curve")
        equity = compute_equity_curve(trades)
        if not equity.empty:
            st.line_chart(equity.set_index("date")["cum_pnl"])

        # P&L distribution by outcome
        col_left, col_right = st.columns(2)
        with col_left:
            st.subheader("P&L by Outcome")
            outcome_summary = closed.groupby("outcome")["pnl_usdc"].sum().reset_index()
            st.bar_chart(outcome_summary.set_index("outcome"))
        with col_right:
            st.subheader("Trades by Strategy")
            if "strategy" in closed.columns:
                strategy_counts = closed["strategy"].value_counts().head(10)
                st.bar_chart(strategy_counts)

    # Open positions summary
    if positions:
        st.subheader("🔵 Open Positions")
        pos_rows = []
        now = datetime.now(timezone.utc).timestamp()
        for token_id, pos in positions.items():
            age_min = (now - pos.get("buy_time", now)) / 60
            pos_rows.append({
                "Token ID": token_id[:12] + "…" if len(token_id) > 12 else token_id,
                "Market": pos.get("market", "Unknown"),
                "Position": pos.get("position", "YES"),
                "Entry Price": pos.get("entry_price"),
                "Size (USDC)": pos.get("size_usdc"),
                "Size (Tokens)": pos.get("size_tokens"),
                "Age (min)": round(age_min, 1),
                "Order ID": (pos.get("order_id") or "")[:10] + "…" if pos.get("order_id") else "",
            })
        pos_df = pd.DataFrame(pos_rows)
        st.dataframe(pos_df, use_container_width=True, hide_index=True)
    else:
        st.caption("No open positions (bot not running or flat)")


# ── Tab 2: Closed Trades ───────────────────────────────────────────────────────
with tab2:
    trades = load_journal()
    if trades.empty:
        st.info("No trades logged yet.")
    else:
        # Filters
        col1, col2, col3 = st.columns(3)
        with col1:
            outcomes = st.multiselect(
                "Outcome",
                options=sorted(trades["outcome"].dropna().unique()),
                default=sorted(trades["outcome"].dropna().unique())
            )
        with col2:
            strategies = st.multiselect(
                "Strategy",
                options=sorted(trades["strategy"].dropna().unique()),
                default=sorted(trades["strategy"].dropna().unique())
            )
        with col3:
            min_date = trades["date"].min().date() if "date" in trades.columns else datetime.now().date()
            max_date = trades["date"].max().date() if "date" in trades.columns else datetime.now().date()
            date_range = st.date_input("Date range", [min_date, max_date])

        # Apply filters
        filtered = trades[
            (trades["outcome"].isin(outcomes)) &
            (trades["strategy"].isin(strategies))
        ]
        if len(date_range) == 2:
            filtered = filtered[
                (filtered["date"].dt.date >= date_range[0]) &
                (filtered["date"].dt.date <= date_range[1])
            ]

        display_cols = [
            "date", "market", "position", "entry_price", "exit_price",
            "size_usdc", "pnl_usdc", "pnl_pct", "outcome", "strategy", "exit_reason", "confidence"
        ]
        # Filter to columns that actually exist
        display_cols = [c for c in display_cols if c in filtered.columns]

        st.dataframe(
            filtered[display_cols].sort_values("date", ascending=False),
            use_container_width=True,
            hide_index=True,
        )

        # Download CSV
        csv = filtered.to_csv(index=False)
        st.download_button("Download CSV", csv, "trades.csv", "text/csv")


# ── Tab 3: Open Positions ──────────────────────────────────────────────────────
with tab3:
    positions = load_positions()
    if not positions:
        st.info("No open positions — bot might not be running or flat.")
    else:
        now = datetime.now(timezone.utc).timestamp()
        pos_rows = []
        for token_id, pos in positions.items():
            age_sec = now - pos.get("buy_time", now)
            pos_rows.append({
                "Token ID": token_id[:14] + "…" if len(token_id) > 14 else token_id,
                "Market": pos.get("market", "Unknown"),
                "Position": pos.get("position", "YES"),
                "Entry Price": pos.get("entry_price"),
                "Size (USDC)": pos.get("size_usdc"),
                "Size (Tokens)": pos.get("size_tokens"),
                "Age": f"{int(age_sec//60)}m {int(age_sec%60)}s",
                "Order ID": (pos.get("order_id") or "—")[:12] + "…" if pos.get("order_id") else "—",
                "Stop Loss %": pos.get("stop_loss_pct", "—"),
                "Take Profit %": pos.get("take_profit_pct", "—"),
            })
        pos_df = pd.DataFrame(pos_rows)
        st.dataframe(pos_df, use_container_width=True, hide_index=True)

        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 Refresh Positions"):
                st.cache_data.clear()
                st.rerun()
        with col2:
            st.caption("Positions auto-refresh every 10 seconds")

st.caption("Data refreshes automatically every 10 seconds. Start the bot to see live updates.")
