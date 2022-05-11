from typing import TYPE_CHECKING

from curio import subprocess

from ..cmdy_defaults import STDOUT, STDERR
from ..cmdy_exceptions import CmdyActionError

if TYPE_CHECKING:
    from ..cmdy_bakeable import Bakeable


def vendor(bakeable: "Bakeable"):
    """Vendor the plugins with the bakeable._plugin_factory"""

    @bakeable._plugin_factory.register
    class PluginValue:
        """Plugins: Value casting
        This is blocking in sync mode
        """

        @bakeable._plugin_factory.run_then
        def str(self, which=None):  # pylint: disable=redefined-builtin
            """Fetch the results as a string"""
            which = which or STDOUT
            if (
                which == STDOUT and self.holding.stdout != subprocess.PIPE
            ) or (which == STDERR and self.holding.stderr != subprocess.PIPE):
                raise CmdyActionError(
                    "Cannot fetch results from " "a redirected PIPE."
                )

            if which not in (STDOUT, STDERR):
                raise CmdyActionError("Expecting STDOUT or STDERR for which.")

            # cached results
            if (
                which == STDOUT
                and getattr(self, "_stdout_str", None) is not None
            ):
                return self._stdout_str
            if (
                which == STDERR
                and getattr(self, "_stderr_str", None) is not None
            ):
                return self._stderr_str

            self.wait()
            out = self.stdout if which == STDOUT else self.stderr
            if isinstance(out, (str, bytes)):
                setattr(
                    self,
                    "_stdout_str" if which == STDOUT else "_stderr_str",
                    out,
                )
                return out

            ret = "".join(out) if self.holding.encoding else b"".join(out)
            setattr(
                self, "_stdout_str" if which == STDOUT else "_stderr_str", ret
            )
            return ret

        @bakeable._plugin_factory.run_then
        async def astr(self, which=None):
            """Async version of str"""

            which = which or STDOUT
            if (
                which == STDOUT and self.holding.stdout != subprocess.PIPE
            ) or (which == STDERR and self.holding.stderr != subprocess.PIPE):
                raise CmdyActionError(
                    "Cannot fetch results from " "a redirected PIPE."
                )

            if which not in (STDOUT, STDERR):
                raise CmdyActionError("Expecting STDOUT or STDERR for which.")

            # cached results
            if (
                which == STDOUT
                and getattr(self, "_stdout_str", None) is not None
            ):
                return self._stdout_str
            if (
                which == STDERR
                and getattr(self, "_stderr_str", None) is not None
            ):
                return self._stderr_str

            await self.wait()
            ret = (
                (await self.stdout.read())
                if which == STDOUT
                else (await self.stderr.read())
            )

            if self.holding.encoding:
                value = ret.decode(self.holding.encoding)
                setattr(
                    self,
                    "_stdout_str" if which == STDOUT else "_stderr_str",
                    value,
                )
                return value

            setattr(
                self, "_stdout_str" if which == STDOUT else "_stderr_str", ret
            )
            return ret

        @bakeable._plugin_factory.add_method(bakeable.CmdyResult)
        def __contains__(self, item):
            return item in self.str()

        @bakeable._plugin_factory.add_method(bakeable.CmdyResult)
        def __eq__(self, other):
            return self.str() == other

        @bakeable._plugin_factory.add_method(bakeable.CmdyResult)
        def __ne__(self, other):
            return not self.__eq__(other)

        @bakeable._plugin_factory.add_method(bakeable.CmdyResult)
        def __str__(self):
            return self.str()

        @bakeable._plugin_factory.add_method(bakeable.CmdyResult)
        def __getattr__(self, name):
            if name in dir("") and not name.startswith("__"):
                return getattr(self.str(), name)
            return self.__getattribute__(name)

        @bakeable._plugin_factory.run_then
        def int(self, which=None):  # pylint: disable=redefined-builtin
            """Cast value to int"""
            return int(self.str(which))

        @bakeable._plugin_factory.run_then
        async def aint(self, which=None):
            """Async version of int"""
            return int(await self.astr(which))

        @bakeable._plugin_factory.run_then
        def float(self, which=None):  # pylint: disable=redefined-builtin
            """Cast value to float"""
            return float(self.str(which))

        @bakeable._plugin_factory.run_then
        async def afloat(self, which=None):
            """Async version of float"""
            return float(await self.astr(which))

    return PluginValue()
