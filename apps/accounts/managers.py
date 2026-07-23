"""Manager for the email-based custom user model."""
from __future__ import annotations

from typing import Any

from django.contrib.auth.base_user import BaseUserManager
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    """User manager that uses email as the unique identifier."""

    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra: Any):
        if not email:
            raise ValueError(_("An email address is required."))
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        if password:
            user.set_password(password)
        else:
            # GHL-provisioned users log in via SSO, not passwords.
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra: Any):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra: Any):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_active", True)
        if extra.get("is_staff") is not True:
            raise ValueError(_("Superuser must have is_staff=True."))
        if extra.get("is_superuser") is not True:
            raise ValueError(_("Superuser must have is_superuser=True."))
        return self._create_user(email, password, **extra)

    def get_by_natural_key(self, username: str):
        return self.get(**{f"{self.model.USERNAME_FIELD}__iexact": username})
