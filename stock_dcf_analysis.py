from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd
import yfinance as yf


@dataclass
class DCFResult:
    stock_symbol: str
    discount_rate: float
    terminal_growth_rate: float
    fcf_growth_rate: float
    latest_fcf: float
    projected_fcfs: List[float]
    discounted_fcfs: List[float]
    pv_of_5y_cash_flows: float
    terminal_value_at_year_5: float
    discounted_terminal_value: float
    enterprise_value: float
    total_debt: float
    cash_and_equivalents: float
    net_debt: float
    equity_value: float
    shares_outstanding: float
    dcf_per_share: float


class DCFCalculationError(Exception):
    pass


def _safe_get_series_value(df: pd.DataFrame, possible_labels: List[str]) -> Optional[pd.Series]:
    """
    Return the first matching row from a financial statement DataFrame.
    """
    if df is None or df.empty:
        return None

    normalized_map = {str(idx).strip().lower(): idx for idx in df.index}

    for label in possible_labels:
        key = label.strip().lower()
        if key in normalized_map:
            return df.loc[normalized_map[key]]

    return None


def _pick_first_number(d: Dict, keys: List[str], default: float = 0.0) -> float:
    for key in keys:
        value = d.get(key)
        if value is not None and pd.notna(value):
            return float(value)
    return float(default)


def _extract_historical_fcf(ticker: yf.Ticker) -> pd.Series:
    """
    Build a historical annual Free Cash Flow series using:
    FCF = Operating Cash Flow + Capital Expenditures

    In yfinance / Yahoo Finance, CapEx is usually already negative.
    """
    cashflow = ticker.cashflow
    if cashflow is None or cashflow.empty:
        raise DCFCalculationError("No annual cash flow statement found from yfinance.")

    ocf_row = _safe_get_series_value(
        cashflow,
        [
            "Operating Cash Flow",
            "Total Cash From Operating Activities",
            "Cash Flow From Continuing Operating Activities",
        ],
    )
    capex_row = _safe_get_series_value(
        cashflow,
        [
            "Capital Expenditure",
            "Capital Expenditures",
            "Purchase Of PPE",
            "Property Plant Equipment",
        ],
    )

    if ocf_row is None:
        raise DCFCalculationError("Operating cash flow row not found in annual cash flow statement.")
    if capex_row is None:
        raise DCFCalculationError("Capital expenditure row not found in annual cash flow statement.")

    ocf = pd.to_numeric(ocf_row, errors="coerce")
    capex = pd.to_numeric(capex_row, errors="coerce")

    # CapEx is typically negative, so FCF = OCF + CapEx
    fcf = (ocf + capex).dropna()

    if fcf.empty:
        raise DCFCalculationError("Unable to compute historical free cash flow values.")

    fcf = fcf.sort_index()
    return fcf


def calculate_5y_dcf(
    stock_symbol: str,
    discount_rate: float,
    terminal_growth_rate: float,
    fcf_growth_rate: float,
    print_summary: bool = True,
) -> DCFResult:
    """
    Calculate a 5-year DCF using yfinance.

    Inputs:
        stock_symbol: ticker symbol, e.g. "VZ"
        discount_rate: decimal, e.g. 0.075 for 7.5%
        terminal_growth_rate: decimal, e.g. 0.02 for 2.0%
        fcf_growth_rate: decimal, e.g. 0.02 for 2.0%
        print_summary: whether to print the summary

    Returns:
        DCFResult
    """
    if discount_rate <= terminal_growth_rate:
        raise ValueError("discount_rate must be greater than terminal_growth_rate.")
    if discount_rate <= 0:
        raise ValueError("discount_rate must be positive.")
    if fcf_growth_rate < -1:
        raise ValueError("fcf_growth_rate is too low; check input.")

    ticker = yf.Ticker(stock_symbol)
    info = ticker.info or {}

    # Historical FCF
    fcf_history = _extract_historical_fcf(ticker)
    latest_fcf = float(fcf_history.iloc[-1])

    if latest_fcf <= 0:
        raise DCFCalculationError(
            f"Latest free cash flow for {stock_symbol.upper()} is non-positive ({latest_fcf:,.0f}). "
            "A standard Gordon-growth DCF is not reliable in this case."
        )

    # Project next 5 years of FCF
    projected_fcfs = []
    current_fcf = latest_fcf
    for _year in range(1, 6):
        current_fcf *= (1 + fcf_growth_rate)
        projected_fcfs.append(current_fcf)

    # Discount each year separately
    discounted_fcfs = [
        fcf / ((1 + discount_rate) ** year)
        for year, fcf in enumerate(projected_fcfs, start=1)
    ]
    pv_of_5y_cash_flows = sum(discounted_fcfs)

    # Terminal value at end of year 5
    fcf_year_6 = projected_fcfs[-1] * (1 + terminal_growth_rate)
    terminal_value_at_year_5 = fcf_year_6 / (discount_rate - terminal_growth_rate)
    discounted_terminal_value = terminal_value_at_year_5 / ((1 + discount_rate) ** 5)

    enterprise_value = pv_of_5y_cash_flows + discounted_terminal_value

    # Balance sheet adjustments
    total_debt = _pick_first_number(
        info,
        ["totalDebt", "longTermDebt", "currentDebt"],
        default=0.0,
    )
    cash_and_equivalents = _pick_first_number(
        info,
        ["totalCash", "cash", "cashAndCashEquivalents"],
        default=0.0,
    )
    net_debt = total_debt - cash_and_equivalents
    equity_value = enterprise_value - net_debt

    shares_outstanding = _pick_first_number(info, ["sharesOutstanding"], default=0.0)
    if shares_outstanding <= 0:
        raise DCFCalculationError("sharesOutstanding not available from yfinance.")

    dcf_per_share = equity_value / shares_outstanding

    result = DCFResult(
        stock_symbol=stock_symbol.upper(),
        discount_rate=discount_rate,
        terminal_growth_rate=terminal_growth_rate,
        fcf_growth_rate=fcf_growth_rate,
        latest_fcf=latest_fcf,
        projected_fcfs=projected_fcfs,
        discounted_fcfs=discounted_fcfs,
        pv_of_5y_cash_flows=pv_of_5y_cash_flows,
        terminal_value_at_year_5=terminal_value_at_year_5,
        discounted_terminal_value=discounted_terminal_value,
        enterprise_value=enterprise_value,
        total_debt=total_debt,
        cash_and_equivalents=cash_and_equivalents,
        net_debt=net_debt,
        equity_value=equity_value,
        shares_outstanding=shares_outstanding,
        dcf_per_share=dcf_per_share,
    )

    if print_summary:
        print_dcf_summary(result)

    return result


def print_dcf_summary(result: DCFResult) -> None:
    def fmt_money(x: float) -> str:
        return f"${x:,.2f}"

    def fmt_rate(x: float) -> str:
        return f"{x * 100:.2f}%"

    print("=" * 72)
    print("DCF SUMMARY")
    print("=" * 72)
    print(f"Stock Symbol:                  {result.stock_symbol}")
    print(f"Discount Rate:                {fmt_rate(result.discount_rate)}")
    print(f"Terminal Growth Rate:         {fmt_rate(result.terminal_growth_rate)}")
    print(f"FCF Growth Rate:              {fmt_rate(result.fcf_growth_rate)}")
    print(f"Latest FCF:                   {fmt_money(result.latest_fcf)}")
    print("-" * 72)
    print("Projected 5-Year FCF:")
    for i, fcf in enumerate(result.projected_fcfs, start=1):
        print(f"  Year {i}:                    {fmt_money(fcf)}")
    print("-" * 72)
    print("Discounted Cash Flows to Today:")
    for i, pv in enumerate(result.discounted_fcfs, start=1):
        print(f"  Year {i} PV:                 {fmt_money(pv)}")
    print(f"Total PV of 5Y Cash Flows:    {fmt_money(result.pv_of_5y_cash_flows)}")
    print("-" * 72)
    print(f"Terminal Value (Year 5):      {fmt_money(result.terminal_value_at_year_5)}")
    print(f"Discounted Terminal Value:    {fmt_money(result.discounted_terminal_value)}")
    print(f"Total Company Value (EV):     {fmt_money(result.enterprise_value)}")
    print("-" * 72)
    print(f"Total Debt:                   {fmt_money(result.total_debt)}")
    print(f"Cash & Equivalents:           {fmt_money(result.cash_and_equivalents)}")
    print(f"Net Debt:                     {fmt_money(result.net_debt)}")
    print(f"Company Value After Debt:     {fmt_money(result.equity_value)}")
    print(f"Shares Outstanding:           {result.shares_outstanding:,.0f}")
    print("=" * 72)
    print(f"DCF PER SHARE:                {fmt_money(result.dcf_per_share)}")
    print("=" * 72)


if __name__ == "__main__":
    try:
        calculate_5y_dcf(
            stock_symbol="T",
            discount_rate=0.075,         # Discount rate = 7.5%
            terminal_growth_rate=0.02,   # Terminal growth = 2%
            fcf_growth_rate=0.02,        # 5-year FCF growth = 2%
            print_summary=True,
        )
    except Exception as e:
        print(f"Error: {e}")
