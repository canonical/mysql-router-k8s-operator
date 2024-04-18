# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Runs logrotate every minute."""

import subprocess
import time


def main():
    """Main watch and dispatch loop.

    Roughly every 60s at the top of the minute, execute logrotate.
    """
    # wait till the top of the minute
    time.sleep(60 - (time.time() % 60))
    start_time = time.monotonic()

    while True:
        subprocess.run(
            [
                "logrotate",
                "-f",
                "-s",
                "/tmp/logrotate.status",
                "/etc/logrotate.d/flush_mysqlrouter_logs",
            ],
            check=True,
        )

        # wait again till the top of the next minute
        time.sleep(60.0 - ((time.monotonic() - start_time) % 60.0))


if __name__ == "__main__":
    main()
