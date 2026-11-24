"""Run migrations and integration tests only against the designated test database."""
import subprocess
import sys
from integration_guard import check_target


def main():
    check_target()
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "integration", "-v"], check=True)


if __name__ == "__main__":
    main()
