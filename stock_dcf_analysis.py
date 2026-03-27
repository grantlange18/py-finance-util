from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd
import yfinance as yf


# Starting FCF = $19.8B
# Growth = 2%
# Discount rate = 7.5%
# Terminal growth = 2%

# Step 1: Project 5-year FCF
# | Year | FCF ($B) |
# | ---- | -------- |
# | 1    | 19.80    |
# | 2    | 20.20    |
# | 3    | 20.60    |
# | 4    | 21.01    |
# | 5    | 21.43    |


# Step 2: Discount to present value
# | Year | PV ($B) |
# | ---- | ------- |
# | 1    | 18.42   |
# | 2    | 17.49   |
# | 3    | 16.56   |
# | 4    | 15.64   |
# | 5    | 14.74   |
# Total PV (5 yrs) ≈ $82.9B
# PV = FCF1/1.075 + FCF2/1.075^2 + FCF3/1.075^3 + FCF4/1.075^4 + FCF5/1.075^5

# Step 3: Terminal value - Gordon Growth Model
# TV = FCF5x(1+g)/(r-g) 
# Where:
# FCF5​= cash flow in year 5
# g = terminal growth rate
# r = discount rate

# Discount terminal value:
# PV = TV/(1+r)^5
# TV=21.43x1.02/(0.075-0.02)​​≈397B
# Discount terminal value: 397/(1.075)^5 ≈276B

# Step 4: Total company value
# PV (5 yrs) = 82.9B
# PV (terminal) = 276B
# Enterprise Value ≈ $359B

# Step 5: Adjust for debt
# Net debt ≈ $120B
# Equity value:359−120=239B

# Step 6: Per-share value
# Shares ≈ 7.2B
# DCF per share: 239/7.2≈33/share

# Final result: DCF value ≈ $32–34 per share


@dataclass
class DCFResult:
    stock_symbol: str
    discount_rate: float
    terminal_growth_rate: float
    fcf_growth_rate: float
    latest_fcf: Optional[float]
    first_year_fcf: float
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

    fcf = (ocf + capex).dropna()

    if fcf.empty:
        raise DCFCalculationError("Unable to compute historical free cash flow values.")

    return fcf.sort_index()


def calculate_5y_dcf(
    stock_symbol: str,
    discount_rate: float,
    terminal_growth_rate: float,
    fcf_growth_rate: float,
    first_year_fcf: Optional[float] = None,
    print_summary: bool = True,
) -> DCFResult:
    """
    Calculate a 5-year DCF.

    Inputs:
        stock_symbol: ticker symbol, e.g. "VZ"
        discount_rate: decimal, e.g. 0.075 for 7.5%
        terminal_growth_rate: decimal, e.g. 0.02 for 2.0%
        fcf_growth_rate: decimal, e.g. 0.02 for 2.0%
        first_year_fcf:
            - if provided, bypass historical FCF retrieval and use this as Year 1 FCF
            - if omitted, retrieve latest FCF from yfinance and project Year 1 from it
        print_summary: whether to print the summary
    """
    if discount_rate <= terminal_growth_rate:
        raise ValueError("discount_rate must be greater than terminal_growth_rate.")
    if discount_rate <= 0:
        raise ValueError("discount_rate must be positive.")
    if first_year_fcf is not None and first_year_fcf <= 0:
        raise ValueError("first_year_fcf must be positive if provided.")

    ticker = yf.Ticker(stock_symbol)
    info = ticker.info or {}

    latest_fcf = None

    # Determine Year 1 FCF
    if first_year_fcf is not None:
        year1_fcf = float(first_year_fcf)
    else:
        fcf_history = _extract_historical_fcf(ticker)
        latest_fcf = float(fcf_history.iloc[-1])

        if latest_fcf <= 0:
            raise DCFCalculationError(
                f"Latest free cash flow for {stock_symbol.upper()} is non-positive ({latest_fcf:,.0f}). "
                "A standard Gordon-growth DCF is not reliable in this case."
            )

        year1_fcf = latest_fcf * (1 + fcf_growth_rate)

    # Build projected FCFs
    projected_fcfs = [year1_fcf]
    current_fcf = year1_fcf
    for _ in range(4):
        current_fcf *= (1 + fcf_growth_rate)
        projected_fcfs.append(current_fcf)

    # Discount each year separately
    discounted_fcfs = [
        fcf / ((1 + discount_rate) ** year)
        for year, fcf in enumerate(projected_fcfs, start=1)
    ]
    pv_of_5y_cash_flows = sum(discounted_fcfs)

    # Terminal value
    fcf_year_6 = projected_fcfs[-1] * (1 + terminal_growth_rate)
    terminal_value_at_year_5 = fcf_year_6 / (discount_rate - terminal_growth_rate)
    discounted_terminal_value = terminal_value_at_year_5 / ((1 + discount_rate) ** 5)

    enterprise_value = pv_of_5y_cash_flows + discounted_terminal_value

    # Balance sheet adjustments still come from yfinance
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
        first_year_fcf=year1_fcf,
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

    if result.latest_fcf is not None:
        print(f"Latest Historical FCF:        {fmt_money(result.latest_fcf)}")
        print(f"Projected Year 1 FCF:         {fmt_money(result.first_year_fcf)}")
    else:
        print(f"Input Year 1 FCF:             {fmt_money(result.first_year_fcf)}")

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
        # Example 1: full yfinance-based starting point
        calculate_5y_dcf(
            stock_symbol="VZ",
            discount_rate=0.075,
            terminal_growth_rate=0.02,
            fcf_growth_rate=0.02,
            print_summary=True,
        )

        # Example 2: bypass historical FCF retrieval, use input Year 1 FCF
        calculate_5y_dcf(
            stock_symbol="VZ",
            discount_rate=0.075,
            terminal_growth_rate=0.02,
            fcf_growth_rate=0.02,
            first_year_fcf=20_000_000_000,
            print_summary=True,
        )

    except Exception as e:
        print(f"Error: {e}")
