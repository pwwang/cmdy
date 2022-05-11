from typing import TYPE_CHECKING

from curio import subprocess

from ..cmdy_defaults import STDOUT, STDERR
from ..cmdy_exceptions import CmdyActionError
from ..cmdy_utils import SyncStreamFromAsync

if TYPE_CHECKING:
    from ..cmdy_bakeable import Bakeable


def vendor(bakeable: "Bakeable"):
    """Vendor the plugins with the bakeable._plugin_factory"""

    @bakeable._plugin_factory.register
    class PluginIter:
        """Plugin: iter
        Iterator over results
        """

        @bakeable._plugin_factory.add_method(bakeable.CmdyResult)
        def __iter__(self):
            return self

        @bakeable._plugin_factory.add_property(bakeable.CmdyResult)
        def stdout(self):
            """Get the iterable of stdout"""

            if self.holding.stdout != subprocess.PIPE:
                # redirected, we are unable to fetch the stdout
                return None

            if self._stdout is not None:
                return self._stdout

            orig_stdout = self._original("stdout")

            if not self.data.get("iter"):
                return orig_stdout.fget(self)

            which = self.data.iter.get("which", STDOUT)
            self._stdout = SyncStreamFromAsync(
                self.proc.stdout, self.holding.encoding
            )
            if which != STDOUT:
                self._stdout = self._stdout.dump()
            return self._stdout

        @bakeable._plugin_factory.add_property(bakeable.CmdyResult)
        def stderr(self):
            """Get the iterable of stderr"""

            if self.holding.stderr != subprocess.PIPE:
                # redirected, we are unable to fetch the stdout
                return None

            if self._stderr is not None:
                return self._stderr

            orig_stderr = self._original("stderr")

            if not self.data.get("iter"):
                return orig_stderr.fget(self)

            which = self.data.iter.get("which", STDOUT)
            self._stderr = SyncStreamFromAsync(
                self.proc.stderr, self.holding.encoding
            )
            if which != STDERR:
                self._stderr = self._stderr.dump()
            return self._stderr

        @bakeable._plugin_factory.add_method(bakeable.CmdyResult)
        def __next__(self):
            return self.next()  # pylint: disable=not-callable

        @bakeable._plugin_factory.add_method(bakeable.CmdyResult)
        def next(self, timeout=None):
            """Get next row, with a timeout limit
            If nothing produced after the timeout, returns an empty string
            """
            which = self.data.get("iter", {}).get("which", STDOUT)
            try:
                if which == STDOUT:
                    if not isinstance(self.stdout, SyncStreamFromAsync):
                        raise TypeError(
                            "CmdyResult object is not iterable "
                            "synchronously"
                        )
                    return self.stdout.next(timeout)

                if not isinstance(self.stderr, SyncStreamFromAsync):
                    raise TypeError(
                        "CmdyResult object is not iterable " "synchronously"
                    )
                return self.stderr.next(timeout)
            except StopIteration:
                # self.data.iter = {}
                self.wait()
                raise

        @bakeable._plugin_factory.run_then("it")
        def iter(self, which=None):  # pylint: disable=redefined-builtin
            """Iterator over STDOUT or STDERR of a CmdyResult object"""

            which = which or STDOUT
            self.data.iter.which = which

            if (
                which == STDOUT and self.holding.stdout != subprocess.PIPE
            ) or (which == STDERR and self.holding.stderr != subprocess.PIPE):
                raise CmdyActionError("Cannot iterate from a redirected PIPE.")

            return self

        @bakeable._plugin_factory.hold_then("it", final=True, hold_right=False)
        def iter_(self, which=None):
            """Put holding on running and iterator over STDOUT or STDERR"""
            self.should_wait = False

            if self._onhold():
                return self
            return self.run().iter(which)

    return PluginIter()
