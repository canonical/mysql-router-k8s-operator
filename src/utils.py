# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Utility functions."""

import sys

python_version_after_3_12 = all((
    sys.version_info[0] == 3,
    sys.version_info[1] >= 12,
))
