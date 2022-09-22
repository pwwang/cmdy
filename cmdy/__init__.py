import sys

from .cmdy_bakeable import Bakeable

__version__ = "0.5.1"

sys.modules[__name__] = Bakeable()  # type: ignore
