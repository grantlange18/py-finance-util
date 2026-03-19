from __future__ import annotations

import csv
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf
from openpyxl import Workbook
from openpyxl.styles import PatternFill


INPUT_FILE = "stocks.csv"
OUTPUT_FILE = "stockchecked.xlsx"

RED_FILL = PatternFill(fill_type="solid", fgColor="FFC7CE")


def parse_money(value: str) -> Optional[float]:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    text = text.replace("$", "").replace(",", "")

    try:
        return float(Decimal(text))
    except (InvalidOperation, ValueError):
        return None


def fetch_prices_batch(symbols: list[str], max_retries: int = 3, delay: int = 5) -> dict[str, Optional[float]]:
    """
    Fetch latest close prices for all symbols in one yfinance call.
    Returns a dict like {"AAPL": 213.49, "SPY": 589.22, "USO": 81.34}
    If a symbol cannot be fetched, it will remain None.
    """
    cleaned = []
    seen = set()

    for s in symbols:
        sym = str(s).strip().upper()
        if sym and sym not in seen:
            cleaned.append(sym)
            seen.add(sym)

    prices = {sym: None for sym in cleaned}
    if not cleaned:
        return prices

    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            df = yf.download(
                tickers=cleaned,
                period="5d",
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                progress=False,
                threads=False,
            )

            if df is None or df.empty:
                raise RuntimeError("No data returned from yfinance")

            # Case 1: multiple tickers -> MultiIndex columns: (Ticker, Field)
            if isinstance(df.columns, pd.MultiIndex):
                for sym in cleaned:
                    try:
                        if sym in df.columns.get_level_values(0):
                            close_series = df[sym]["Close"].dropna()
                            if not close_series.empty:
                                prices[sym] = float(close_series.iloc[-1])
                    except Exception:
                        pass

            # Case 2: single ticker -> normal columns: Open, High, Low, Close...
            else:
                if len(cleaned) == 1 and "Close" in df.columns:
                    close_series = df["Close"].dropna()
                    if not close_series.empty:
                        prices[cleaned[0]] = float(close_series.iloc[-1])

            return prices

        except Exception as e:
            last_error = e
            if attempt < max_retries:
                sleep_seconds = delay * attempt
                print(f"Batch fetch attempt {attempt} failed: {e}")
                print(f"Retrying in {sleep_seconds} seconds...")
                time.sleep(sleep_seconds)

    print(f"Batch fetch failed after {max_retries} attempts: {last_error}")
    return prices


def autosize_columns(ws) -> None:
    for column_cells in ws.columns:
        max_length = 0
        column_letter = column_cells[0].column_letter
        for cell in column_cells:
            value = "" if cell.value is None else str(cell.value)
            max_length = max(max_length, len(value))
        ws.column_dimensions[column_letter].width = min(max_length + 2, 40)


def main() -> None:
    input_path = Path(INPUT_FILE)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {INPUT_FILE}")

    with input_path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if not rows:
        raise ValueError("The input CSV is empty.")

    header = rows[0]
    if len(header) < 3:
        raise ValueError(
            "The input CSV must have at least 3 columns: "
            "'Stocks/ETF', 'Target Low', 'Target High'."
        )

    # Gather all symbols once
    symbols = []
    for row in rows[1:]:
        if row and len(row) > 0:
            symbols.append(row[0])

    price_map = fetch_prices_batch(symbols)

    output_header = header[:3] + ["Current Price"] + header[3:]

    wb = Workbook()
    ws = wb.active
    ws.title = "Stock Check"
    ws.append(output_header)
    ws.freeze_panes = "A2"

    for row in rows[1:]:
        padded_row = row + [""] * max(0, len(header) - len(row))

        symbol = str(padded_row[0]).strip().upper()
        target_low = parse_money(padded_row[1])
        target_high = parse_money(padded_row[2])
        current_price = price_map.get(symbol)

        # Put a readable marker if price could not be retrieved
        current_price_output = current_price if current_price is not None else "RATE LIMITED / NO DATA"

        output_row = padded_row[:3] + [current_price_output] + padded_row[3:]
        ws.append(output_row)

        excel_row = ws.max_row

        ws.cell(excel_row, 2).number_format = '$#,##0.00'
        ws.cell(excel_row, 3).number_format = '$#,##0.00'
        if isinstance(current_price, (int, float)):
            ws.cell(excel_row, 4).number_format = '$#,##0.00'

        # Red row if outside range
        if (
            current_price is not None
            and target_low is not None
            and target_high is not None
            and (current_price < target_low or current_price > target_high)
        ):
            for col in range(1, len(output_header) + 1):
                ws.cell(excel_row, col).fill = RED_FILL

    autosize_columns(ws)
    wb.save(OUTPUT_FILE)
    print(f"Done. Output written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
