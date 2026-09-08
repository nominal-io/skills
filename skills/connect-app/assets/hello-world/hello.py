"""Minimal Connect script: reads a UI value, writes a UI banner, streams a signal."""

import math
import time

import connect_python


logger = connect_python.get_logger(__name__)


@connect_python.main
def main(client: connect_python.Client):
    name = client.get_value("user_name", "World")
    logger.info(f"Hello, {name}")

    client.set_value("hello_output", f"Hello, {name}!")

    # Stream a 1 Hz sine wave for 30 seconds to the `signal` stream.
    start = time.time()
    while time.time() - start < 30.0:
        t = time.time()
        client.stream("signal", t, math.sin(t - start), name="value")
        time.sleep(0.05)


if __name__ == "__main__":
    main()
