# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Utility functions."""

import secrets
import string
import sys

python_version_after_3_12 = all((
    sys.version_info[0] == 3,
    sys.version_info[1] >= 12,
))


def generate_password() -> str:
    """Generate a random password."""
    choices = string.ascii_letters + string.digits
    return "".join(secrets.choice(choices) for _ in range(24))
