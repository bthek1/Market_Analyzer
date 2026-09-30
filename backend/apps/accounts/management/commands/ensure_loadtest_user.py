"""Create or refresh the dedicated load-test account (issue #12).

Load runs never use a real account: the k6 scripts log in as LOADTEST_EMAIL, and this
command makes that user exist with LOADTEST_PASSWORD. Idempotent - re-running it resets
the password to the environment's value, so rotating the secret is one command.

Two refusals keep it from ever touching a real account:
- the address's local part must start with "loadtest", and
- an existing staff or superuser account at that address is an error, never demoted.
"""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

DEFAULT_EMAIL = "loadtest@stockmarket.local"


class Command(BaseCommand):
    help = "Create or refresh the non-staff load-test user from LOADTEST_EMAIL/LOADTEST_PASSWORD."

    def handle(self, *args, **options):
        email = os.getenv("LOADTEST_EMAIL") or DEFAULT_EMAIL
        password = os.getenv("LOADTEST_PASSWORD")
        if not password:
            raise CommandError("LOADTEST_PASSWORD is not set")
        if not email.split("@", 1)[0].lower().startswith("loadtest"):
            raise CommandError(
                f"{email!r} does not look like a load-test account; its local part must "
                "start with 'loadtest' so this command can never reset a real user's password"
            )

        user_model = get_user_model()
        user = user_model.objects.filter(email__iexact=email).first()
        if user is not None and (user.is_staff or user.is_superuser):
            raise CommandError(f"{email} is a staff/superuser account; refusing to use it")

        if user is None:
            user_model.objects.create_user(email=email, password=password)
            self.stdout.write(self.style.SUCCESS(f"Created load-test user {email}"))
            return

        user.set_password(password)
        user.is_active = True
        user.save(update_fields=["password", "is_active"])
        self.stdout.write(self.style.SUCCESS(f"Refreshed load-test user {email}"))
