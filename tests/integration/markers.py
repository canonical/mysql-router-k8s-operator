# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest

from . import juju_

skip_juju_2_9 = pytest.mark.skipif(juju_.is_2_9, reason="Skips juju v2.9.x")
