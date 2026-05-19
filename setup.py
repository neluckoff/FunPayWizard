from pathlib import Path

from pip._internal.cli.main import main


def install_packages():
    requirements = Path(__file__).parent / "requirements.txt"
    main(["install", "-U", "-r", str(requirements)])


if __name__ == "__main__":
    install_packages()
