import uuid
from typing import ClassVar

from django.db import models

from .choices import Currency, Exchange, Period, StatementType


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Sector(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class Industry(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    sector = models.ForeignKey(
        Sector,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="industries",
    )

    class Meta:
        ordering = ("name",)
        verbose_name_plural = "industries"

    def __str__(self):
        return self.name


class Company(TimeStampedModel):
    Exchange = Exchange
    Currency = Currency

    symbol = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200, blank=True)
    exchange = models.CharField(max_length=20, choices=Exchange.choices, blank=True, default="")
    currency = models.CharField(max_length=10, choices=Currency.choices, blank=True, default="")
    is_bootstrapped = models.BooleanField(default=False, db_index=True)
    sector = models.ForeignKey(
        Sector,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="companies",
    )
    industry = models.ForeignKey(
        Industry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="companies",
    )

    # Contact / identity
    address = models.CharField(max_length=255, blank=True, default="")
    city = models.CharField(max_length=100, blank=True, default="")
    state = models.CharField(max_length=50, blank=True, default="")
    zip_code = models.CharField(max_length=20, blank=True, default="")
    country = models.CharField(max_length=100, blank=True, default="")
    phone = models.CharField(max_length=50, blank=True, default="")
    website = models.URLField(blank=True, default="")
    ir_website = models.URLField(blank=True, default="")
    description = models.TextField(blank=True, default="")
    full_time_employees = models.IntegerField(null=True)
    officers = models.JSONField(default=list)

    class Meta:
        ordering = ("symbol",)
        verbose_name_plural = "companies"

    def __str__(self):
        return self.symbol


class PriceBar(TimeStampedModel):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="prices")
    date = models.DateField()
    open = models.DecimalField(max_digits=14, decimal_places=4)
    high = models.DecimalField(max_digits=14, decimal_places=4)
    low = models.DecimalField(max_digits=14, decimal_places=4)
    close = models.DecimalField(max_digits=14, decimal_places=4)
    volume = models.BigIntegerField()

    class Meta:
        unique_together = ("company", "date")
        indexes = (models.Index(fields=["company", "date"]),)


class CompanySnapshot(TimeStampedModel):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="snapshots")
    fetched_at = models.DateTimeField(auto_now_add=True)

    market_cap = models.BigIntegerField(null=True)
    trailing_pe = models.FloatField(null=True)
    forward_pe = models.FloatField(null=True)
    price_to_book = models.FloatField(null=True)
    debt_to_equity = models.FloatField(null=True)
    return_on_equity = models.FloatField(null=True)
    profit_margins = models.FloatField(null=True)
    dividend_yield = models.FloatField(null=True)
    trailing_eps = models.FloatField(null=True)
    forward_eps = models.FloatField(null=True)

    # Valuation extensions
    beta = models.FloatField(null=True)
    fifty_two_week_high = models.FloatField(null=True)
    fifty_two_week_low = models.FloatField(null=True)
    week52_change = models.FloatField(null=True)
    sandp52_week_change = models.FloatField(null=True)
    average_volume = models.BigIntegerField(null=True)
    shares_outstanding = models.BigIntegerField(null=True)
    float_shares = models.BigIntegerField(null=True)
    enterprise_value = models.BigIntegerField(null=True)
    enterprise_to_revenue = models.FloatField(null=True)
    enterprise_to_ebitda = models.FloatField(null=True)
    peg_ratio = models.FloatField(null=True)
    trailing_peg_ratio = models.FloatField(null=True)
    price_to_sales = models.FloatField(null=True)
    payout_ratio = models.FloatField(null=True)
    book_value = models.FloatField(null=True)

    # Technical moving averages
    fifty_day_average = models.FloatField(null=True)
    two_hundred_day_average = models.FloatField(null=True)

    # Growth
    revenue_growth = models.FloatField(null=True)
    earnings_growth = models.FloatField(null=True)
    earnings_quarterly_growth = models.FloatField(null=True)

    # Margins
    gross_margins = models.FloatField(null=True)
    operating_margins = models.FloatField(null=True)
    ebitda_margins = models.FloatField(null=True)

    # Liquidity
    current_ratio = models.FloatField(null=True)
    quick_ratio = models.FloatField(null=True)

    # Profitability
    return_on_assets = models.FloatField(null=True)
    ebitda = models.BigIntegerField(null=True)
    total_cash = models.BigIntegerField(null=True)
    total_cash_per_share = models.FloatField(null=True)
    free_cashflow = models.BigIntegerField(null=True)
    operating_cashflow = models.BigIntegerField(null=True)
    net_income_to_common = models.BigIntegerField(null=True)
    revenue_per_share = models.FloatField(null=True)

    # Ownership
    held_pct_institutions = models.FloatField(null=True)
    held_pct_insiders = models.FloatField(null=True)

    # Dividend snapshot
    dividend_rate = models.FloatField(null=True)
    ex_dividend_date = models.DateField(null=True)
    five_year_avg_dividend_yield = models.FloatField(null=True)
    trailing_annual_dividend_rate = models.FloatField(null=True)
    last_dividend_value = models.FloatField(null=True)
    last_dividend_date = models.DateField(null=True)

    # Fiscal calendar
    last_fiscal_year_end = models.DateField(null=True)
    next_fiscal_year_end = models.DateField(null=True)
    most_recent_quarter = models.DateField(null=True)

    # Governance risk scores (1-10, lower is better)
    audit_risk = models.SmallIntegerField(null=True)
    board_risk = models.SmallIntegerField(null=True)
    compensation_risk = models.SmallIntegerField(null=True)
    shareholder_rights_risk = models.SmallIntegerField(null=True)
    overall_risk = models.SmallIntegerField(null=True)

    # Analyst consensus
    recommendation_mean = models.FloatField(null=True)
    recommendation_key = models.CharField(max_length=20, null=True)
    num_analyst_opinions = models.IntegerField(null=True)
    target_high_price = models.FloatField(null=True)
    target_low_price = models.FloatField(null=True)
    target_mean_price = models.FloatField(null=True)
    target_median_price = models.FloatField(null=True)
    recommendations_breakdown = models.JSONField(default=list)

    # Split history
    last_split_factor = models.CharField(max_length=20, null=True)
    last_split_date = models.DateField(null=True)

    raw = models.JSONField()

    class Meta:
        ordering = ("-fetched_at",)
        indexes = (models.Index(fields=["company", "fetched_at"]),)


class FinancialStatement(TimeStampedModel):
    StatementType = StatementType
    Period = Period

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="financials")
    statement_type = models.CharField(max_length=10, choices=StatementType)
    period = models.CharField(max_length=10, choices=Period)
    period_end = models.DateField()
    metric = models.CharField(max_length=100)
    value = models.FloatField(null=True)

    class Meta:
        unique_together = ("company", "statement_type", "period", "period_end", "metric")
        indexes = (models.Index(fields=["company", "statement_type", "period_end"]),)


class Dividend(TimeStampedModel):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="dividends")
    date = models.DateField()
    amount = models.DecimalField(max_digits=10, decimal_places=4)

    class Meta:
        unique_together = ("company", "date")


class CompanySummary(TimeStampedModel):
    class Verdict(models.TextChoices):
        BUY = "buy", "Buy"
        HOLD = "hold", "Hold"
        SELL = "sell", "Sell"
        INSUFFICIENT_DATA = "insufficient_data", "Insufficient Data"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="summaries")
    generated_at = models.DateTimeField(auto_now_add=True)
    model_name = models.CharField(max_length=100)
    verdict = models.CharField(max_length=20, choices=Verdict.choices)
    # 0-1, as reported by the model in its structured response. Null when the response
    # carried no usable confidence (or the summary never reached the LLM).
    confidence = models.FloatField(null=True)
    summary = models.TextField()
    key_risks = models.JSONField(default=list)
    key_drivers = models.JSONField(default=list)
    data_snapshot = models.JSONField()

    class Meta:
        ordering = ("-generated_at",)
        indexes = (models.Index(fields=["company", "generated_at"]),)


class ShortInterest(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="short_interest")
    fetched_at = models.DateTimeField()
    date_short_interest = models.DateField(null=True)
    shares_short = models.BigIntegerField(null=True)
    shares_short_prior_month = models.BigIntegerField(null=True)
    short_ratio = models.FloatField(null=True)
    short_pct_of_float = models.FloatField(null=True)
    shares_pct_shares_out = models.FloatField(null=True)

    class Meta:
        ordering = ("-fetched_at",)
        indexes = (models.Index(fields=["company", "fetched_at"]),)


class InstitutionalHolderSnapshot(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="institutional_holder_snapshots"
    )
    fetched_at = models.DateTimeField()
    holders = models.JSONField(default=list)

    class Meta:
        ordering = ("-fetched_at",)
        indexes = (models.Index(fields=["company", "fetched_at"]),)


class EarningsDate(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="earnings_dates")
    earnings_date = models.DateField()
    eps_estimate = models.FloatField(null=True)
    reported_eps = models.FloatField(null=True)
    surprise_pct = models.FloatField(null=True)
    is_upcoming = models.BooleanField(default=False)
    fetched_at = models.DateTimeField(null=True)

    class Meta:
        unique_together = ("company", "earnings_date")
        ordering = ("-earnings_date",)
        indexes = (models.Index(fields=["company", "is_upcoming"]),)


class OptionsExpiry(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="options_expiries")
    expiry_date = models.DateField()
    fetched_at = models.DateTimeField()

    class Meta:
        unique_together = ("company", "expiry_date", "fetched_at")
        ordering = ("expiry_date",)


class CompanySyncRecord(TimeStampedModel):
    SYNC_TYPE_CHOICES: ClassVar[list] = [
        ("price", "Price"),
        ("snapshot", "Snapshot"),
        ("profile", "Profile"),
        ("financials", "Financials"),
        ("dividends", "Dividends"),
        ("earnings_dates", "Earnings Dates"),
        ("institutional_holders", "Institutional Holders"),
        ("options", "Options"),
        ("short_interest", "Short Interest"),
    ]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="sync_records")
    sync_type = models.CharField(max_length=30, choices=SYNC_TYPE_CHOICES)
    last_synced_at = models.DateTimeField()

    class Meta:
        unique_together: ClassVar[list] = [("company", "sync_type")]
        indexes: ClassVar[list] = [
            models.Index(fields=["sync_type", "last_synced_at"]),
        ]

    def __str__(self):
        return f"{self.company.symbol} / {self.sync_type}"


class OptionsContract(TimeStampedModel):
    class OptionType(models.TextChoices):
        CALL = "call", "Call"
        PUT = "put", "Put"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    expiry = models.ForeignKey(OptionsExpiry, on_delete=models.CASCADE, related_name="contracts")
    option_type = models.CharField(max_length=4, choices=OptionType.choices)
    contract_symbol = models.CharField(max_length=30)
    strike = models.DecimalField(max_digits=12, decimal_places=2)
    last_price = models.DecimalField(max_digits=12, decimal_places=4, null=True)
    bid = models.DecimalField(max_digits=12, decimal_places=4, null=True)
    ask = models.DecimalField(max_digits=12, decimal_places=4, null=True)
    volume = models.IntegerField(null=True)
    open_interest = models.IntegerField(null=True)
    implied_volatility = models.FloatField(null=True)
    in_the_money = models.BooleanField(null=True)

    class Meta:
        unique_together = ("expiry", "option_type", "contract_symbol")
        indexes = (models.Index(fields=["expiry", "option_type", "strike"]),)
