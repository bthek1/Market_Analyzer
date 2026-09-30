import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [  # noqa: RUF012
        ("companies", "0001_initial"),
    ]

    operations = [  # noqa: RUF012
        # Sector
        migrations.AddField(
            model_name="sector",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="sector",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        # Industry
        migrations.AddField(
            model_name="industry",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="industry",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        # Company
        migrations.AddField(
            model_name="company",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="company",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        # PriceBar
        migrations.AddField(
            model_name="pricebar",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="pricebar",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        # CompanySnapshot
        migrations.AddField(
            model_name="companysnapshot",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="companysnapshot",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        # FinancialStatement
        migrations.AddField(
            model_name="financialstatement",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="financialstatement",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        # Dividend
        migrations.AddField(
            model_name="dividend",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="dividend",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
    ]
