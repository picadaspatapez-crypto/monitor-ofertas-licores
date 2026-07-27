"""Application release metadata.

Keep ``APP_VERSION`` for backwards compatibility and expose ``__version__``
for the pipeline banner and any external tooling that follows the conventional
Python version attribute.
"""

APP_VERSION = "4.4.3"
__version__ = APP_VERSION
RELEASE_NAME = "Performance Engine · Playwright Wait Fix"
