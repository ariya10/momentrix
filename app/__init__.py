"""MOMENTRIX local clipping application."""


def __getattr__(name: str):
    if name == "app":
        from app.main import app

        return app
    raise AttributeError(name)
