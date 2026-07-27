from app.pipeline.runner import run_pipeline


def run() -> int:
    """Compatibilidad con el punto de entrada v1."""
    return run_pipeline()
