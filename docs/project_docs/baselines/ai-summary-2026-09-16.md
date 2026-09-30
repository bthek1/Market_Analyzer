# AI Summary Baseline - 2026-09-16

Single-call `generate_company_summary` outputs captured **before** the issue #1 rewrite, on
`qwen3:8b` via `_SUMMARY_SYSTEM_PROMPT` + `_build_prompt_text`. Generated without persisting
`CompanySummary` rows. See [`../ai-summary-pipeline.md`](../ai-summary-pipeline.md) for the path
and the findings.

**All five tickers returned `buy`**, consistent with the 60% buy / 1.1% sell distribution across
the 1,236 summaries already in the DB.

Each run also repeated at least one of the unit bugs as if it were a real, bullish fact - see the
quotes collected at the bottom.

### AAPL - Apple Inc.

- verdict: `buy` | latency: 13.4s | prompt: 2345 chars (~586 tokens)

```
Apple Inc. (AAPL) exhibits strong profitability with high profit and operating margins, alongside a robust return on equity and assets. Recent financial performance shows solid revenue and earnings growth, with a 16.4% year-over-year revenue increase and 28.7% earnings growth. The company maintains a healthy liquidity position with a current ratio of 1.00 and a strong cash reserve. However, its debt-to-equity ratio of 78.44 indicates significant leverage. The stock is currently trading above its 52-week low, with analyst consensus favoring a "buy" recommendation. The forward P/E ratio of 32.94 and a high dividend yield of 34.0% suggest investor confidence. Despite a high price-to-book ratio and peg ratio, the recent earnings surprise of 674% highlights potential upside. With upcoming earnings on the horizon, the stock remains a compelling candidate for growth-oriented investors.

VERDICT: BUY
```

### MSFT - Microsoft Corporation

- verdict: `buy` | latency: 5.1s | prompt: 2358 chars (~589 tokens)

```
Microsoft Corporation (MSFT) demonstrates strong financial health and profitability, with a trailing P/E of 27.85 and a forward P/E of 21.30, indicating reasonable valuation relative to future earnings. The company maintains high profit margins (40.3%) and operating margins (45.1%), alongside robust return metrics (ROE: 34.0%, ROA: 14.1%). Recent revenue and earnings growth of 17.7% and 31.7% respectively, further support its strong performance. Free cash flow remains consistently high, with $66.99B in the most recent quarter. The company's debt-to-equity ratio of 29.12 suggests moderate leverage, while liquidity ratios (current ratio: 1.23, quick ratio: 1.10) are acceptable. Analysts overwhelmingly recommend a "strong buy," with a mean target price of $563.84. The recent earnings surprise of 1,181% highlights exceptional performance. With solid fundamentals and strong analyst support, Microsoft remains an attractive investment.  

VERDICT: BUY
```

### KO - The Coca-Cola Company

- verdict: `buy` | latency: 4.7s | prompt: 2327 chars (~581 tokens)

```
The Coca-Cola Company (KO) is a well-established player in the beverages sector with strong profitability metrics, including a 28.6% profit margin and a 34.9% operating margin. Its recent earnings growth of 16.9% and a 6.7% revenue growth highlight solid performance. The company's forward P/E of 24.69 and a price-to-book ratio of 10.36 suggest it is trading at a premium, though its low beta of 0.34 indicates low volatility. KO offers a high dividend yield of 244.0%, though the payout ratio of 62.5% suggests some caution regarding sustainability. Despite a high debt-to-equity ratio of 115.52, the company maintains a healthy current ratio of 1.30. Analysts overwhelmingly recommend a "buy," with a mean target price of $94.70. Recent strong earnings surprises and robust free cash flow further support its financial health. 

VERDICT: BUY
```

### XOM - ExxonMobil Holdings Corporation

- verdict: `buy` | latency: 4.8s | prompt: 2336 chars (~584 tokens)

```
ExxonMobil Holdings Corporation (XOM) presents a compelling case for investment due to its strong financial performance and favorable valuation metrics. The company has delivered impressive year-over-year revenue and earnings growth of 44.1% and 112.8%, respectively, reflecting robust operational performance. Its trailing P/E ratio of 25.76 and forward P/E of 14.46 suggest a mix of current earnings and future growth potential. The price-to-book ratio of 2.43 and a low beta of 0.17 indicate reasonable valuation and low volatility. With a 269% dividend yield and a 68% payout ratio, XOM offers significant income generation. Analysts overwhelmingly recommend a "buy" with a mean target of $168.32. Despite a high debt-to-equity ratio of 15.92, the company's strong liquidity and free cash flow support its financial stability. The recent earnings surprise of 1326% further highlights its strong performance. 

VERDICT: BUY
```

### JPM - JPMorgan Chase & Co.

- verdict: `buy` | latency: 5.0s | prompt: 2163 chars (~540 tokens)

```
JPMorgan Chase & Co. (JPM) is a large diversified bank with a strong market position and robust financials. Its trailing and forward P/E ratios are reasonable at 15.10 and 14.11, respectively, while the price-to-book ratio of 2.65 suggests it is trading at a slight premium to book value. The company has shown strong growth, with earnings up 46.9% year-over-year and revenue rising 30.4%. Profitability is solid, with operating margins at 50.4% and return on equity of 17.8%. The dividend yield is unusually high at 171.0%, likely due to a special dividend, with a payout ratio of 25.7%, indicating sustainable dividend policy. Analysts are overwhelmingly bullish, with a buy recommendation and target price range of $305 to $452. However, free cash flow has been negative in recent quarters, and leverage data is not available. Despite this, the strong earnings surprise and positive analyst sentiment support a favorable outlook. 

VERDICT: BUY
```

## Unit bugs the model repeated as fact

Direct quotes from the runs above. None of these numbers are real; each is a
`_fmt(pct=True)` 100x error or a percent-vs-ratio confusion (see finding #1 in the main doc).

| Ticker | Quote | Reality |
|---|---|---|
| AAPL | "a high dividend yield of **34.0%** suggest investor confidence" | 0.34% |
| AAPL | "the recent earnings surprise of **674%** highlights potential upside" | +6.74% |
| MSFT | "The recent earnings surprise of **1,181%** highlights exceptional performance" | +11.81% |
| KO | "KO offers a high dividend yield of **244.0%**" | 2.44% |
| XOM | "With a **269% dividend yield** ... XOM offers significant income generation" | 2.69% |
| XOM | "the recent earnings surprise of **1326%**" | +13.26% |
| XOM | "Despite a **high** debt-to-equity ratio of 15.92" | 0.16x - very low leverage |
| JPM | "The dividend yield is unusually high at **171.0%**, likely due to a special dividend" | 1.71% - and the explanation is invented |
| AAPL | "its debt-to-equity ratio of **78.44** indicates significant leverage" | 0.78x - normal |
| KO | "Despite a **high** debt-to-equity ratio of **115.52**" | 1.16x - moderate |

The JPM line is the clearest illustration of the risk: rather than flagging an impossible value,
the model **invented a plausible-sounding cause** ("likely due to a special dividend") for a
rendering bug.
