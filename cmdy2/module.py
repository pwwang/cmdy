from __future__ import annotations

import re
import sys
import logging
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from varname import varname, ImproperUseError, VarnameRetrievingError

from .core import Cmdy


class CmdyModule(ModuleType):

    def __init__(self, name: str, doc: str | None = None):
        super().__init__(name, doc)
        self.__path__ = []
        self.__file__ = str(Path(__file__).parent.joinpath("__init__.py"))
        self.__config__ = {}
        self.__logger__ = logging.getLogger(name)
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        ))
        self.__logger__.addHandler(handler)

    def __call__(self, **kwargs) -> CmdyModule:
        """Baking a new module"""
        config = deepcopy(self.__config__)
        config.update(kwargs)
        # Calculate the new module name
        try:
            name = varname()
        except (ImproperUseError, VarnameRetrievingError):
            if match := re.match(r"^(.+)_baked(\d+)?$", self.__name__):
                name = f"{match.group(1)}_baked{int(match.group(2) or 0) + 1}"
            else:
                name = f"{self.__name__}_baked"

        module = self.__class__(name)
        module.__config__ = config
        return module

    def __getattr__(self, name):
        """Create a Cmdy object"""
        caller = sys._getframe(1)
        # https://stackoverflow.com/a/60803436/5088165
        if caller.f_globals['__name__'].startswith("importlib."):
            return super().__getattr__(name)

        return Cmdy(name, self.__config__, self.__logger__)
