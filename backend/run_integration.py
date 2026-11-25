"""Run migrations and integration tests only against the designated test database."""
import subprocess
import sys
from integration_guard import check_target


def main():
    check_target()
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    # Keep database tests in fresh processes. Discovering the whole directory
    # also imports isolated pytest modules that replace the database URL while
    # importing app.db; that can cache an unintended engine before these tests.
    for filename in ("test_api.py", "test_pipeline.py"):
        subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "integration",
                        "-p", filename, "-v"], check=True)


if __name__ == "__main__":
    main()
