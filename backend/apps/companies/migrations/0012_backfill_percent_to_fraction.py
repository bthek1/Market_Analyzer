"""Backfill CompanySnapshot ratios that were stored in percent.

``dividend_yield``, ``five_year_avg_dividend_yield`` and ``debt_to_equity`` arrive from
yfinance scaled to percent. Until the ingestion fix they were stored verbatim, so every
reader that treated them as fractions rendered them 100x too large (a 0.44% yield read as
44%). Ingestion now divides by 100; this rescales the rows written before that.

Reverse multiplies back by 100 so the pair is symmetric.
"""

from django.db import migrations

_FIELDS = ("dividend_yield", "five_year_avg_dividend_yield", "debt_to_equity")


def _scale(apps, factor):
    from django.db.models import F

    CompanySnapshot = apps.get_model("companies", "CompanySnapshot")
    for field in _FIELDS:
        CompanySnapshot.objects.filter(**{f"{field}__isnull": False}).update(
            **{field: F(field) * factor}
        )


def to_fraction(apps, schema_editor):
    _scale(apps, 0.01)


def to_percent(apps, schema_editor):
    _scale(apps, 100.0)


class Migration(migrations.Migration):
    dependencies = [
        ("companies", "0011_companysummary_created_at_companysummary_updated_at_and_more"),
    ]

    operations = [
        migrations.RunPython(to_fraction, to_percent),
    ]
