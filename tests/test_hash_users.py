import os
import subprocess
import sys


def test_hash_users_never_writes_raw_ids(tmp_path):
    source = tmp_path / "behaviors.tsv"
    output = tmp_path / "hashed.tsv"
    source.write_text("1\tuser-raw-1\t2020-01-01 00:00:00\t\tN1-1 N2-0\n")
    env = dict(os.environ, MIND_USER_HASH_SALT="test-salt")
    subprocess.check_call([sys.executable, "scripts/hash_users.py",
                           "--input", str(source), "--output", str(output)], env=env)
    assert "user-raw-1" not in output.read_text()
