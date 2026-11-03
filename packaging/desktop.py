"""PyInstaller entry point: reserve/reuse the port before opening projects."""
from oclast.launcher import run


def create_app():
    from api import app
    return app


if __name__ == '__main__':
    run(create_app)
