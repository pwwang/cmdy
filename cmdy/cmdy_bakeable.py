from threading import Event

from .cmdy_plugin import PluginFactory
from .cmdy_plugins import register_plugins
from .cmdy_exceptions import (
    CmdyActionError,
    CmdyTimeoutError,
    CmdyExecNotFoundError,
    CmdyReturnCodeError,
)
from .cmdy_defaults import STDIN, STDOUT, STDERR, DEVNULL
from .cmdy_plugin import pluginable
from .cmdy_result import CmdyResult, CmdyAsyncResult
from .cmdy_utils import new_class
from .cmdy import Cmdy, CmdyHolding


class Bakeable:
    def __init__(self, **baking_args):
        self.CmdyActionError = CmdyActionError
        self.CmdyTimeoutError = CmdyTimeoutError
        self.CmdyExecNotFoundError = CmdyExecNotFoundError
        self.CmdyReturnCodeError = CmdyReturnCodeError
        self.CmdyResult = pluginable(
            new_class(CmdyResult, data={"__module__": "cmdy"})
        )
        self.CmdyHolding = pluginable(
            new_class(CmdyHolding, data={"__module__": "cmdy"})
        )
        self.Cmdy = Cmdy
        self.STDIN = STDIN
        self.STDOUT = STDOUT
        self.STDERR = STDERR
        self.DEVNULL = DEVNULL
        self._event = Event()
        self._baking_args = baking_args
        self._holding_left = ["a", "async_", "h", "hold"]
        self._holding_right = []
        self._holding_finals = []
        self._result_finals = []
        # init plugins
        self._plugin_factory = PluginFactory(self)
        self._plugins = register_plugins(self)
        self.CmdyAsyncResult = new_class(
            self.CmdyResult,
            "CmdyAsyncResult",
            {"__module__": "cmdy", **CmdyAsyncResult.__dict__},
        )

    def __call__(self, **baking_args):
        return self.__class__(**baking_args)

    def __getattr__(self, name: str):
        if name.startswith("__"):
            try:
                return globals()[name]
            except KeyError:
                raise AttributeError
        return self.Cmdy(name, bakeable=self)
