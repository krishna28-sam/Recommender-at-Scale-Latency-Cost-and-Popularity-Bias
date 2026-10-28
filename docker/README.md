# Runtime notes

The target runtime is Python 3.11. The pinned `apache-flink==1.20.1` package is
used with the official Flink 1.20 Python support range of Python 3.8, 3.9,
3.10, and 3.11. The Flink image therefore uses Python 3.11. This statement is
based on the Apache Flink 1.20 installation documentation and should be
rechecked if the pin changes.
