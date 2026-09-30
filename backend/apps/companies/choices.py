from django.db import models


class Exchange(models.TextChoices):
    NYSE = "NYSE", "New York Stock Exchange"
    NASDAQ = "NASDAQ", "NASDAQ"
    AMEX = "AMEX", "American Stock Exchange"
    NYSE_ARCA = "NYSE_ARCA", "NYSE Arca"
    LSE = "LSE", "London Stock Exchange"
    ASX = "ASX", "Australian Securities Exchange"
    TSX = "TSX", "Toronto Stock Exchange"
    OTHER = "OTHER", "Other"


class Currency(models.TextChoices):
    USD = "USD", "US Dollar"
    EUR = "EUR", "Euro"
    GBP = "GBP", "British Pound"
    AUD = "AUD", "Australian Dollar"
    CAD = "CAD", "Canadian Dollar"
    JPY = "JPY", "Japanese Yen"
    CHF = "CHF", "Swiss Franc"
    HKD = "HKD", "Hong Kong Dollar"
    CNY = "CNY", "Chinese Yuan"
    OTHER = "OTHER", "Other"


class StatementType(models.TextChoices):
    INCOME = "income", "Income Statement"
    BALANCE = "balance", "Balance Sheet"
    CASHFLOW = "cashflow", "Cash Flow"


class Period(models.TextChoices):
    ANNUAL = "annual", "Annual"
    QUARTERLY = "quarterly", "Quarterly"
