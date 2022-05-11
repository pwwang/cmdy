import sys
import fileinput
import warnings
from typing import TYPE_CHECKING, Union

import curio
from curio import subprocess

from ..cmdy_exceptions import CmdyTimeoutError

if TYPE_CHECKING:
    from ..cmdy_bakeable import Bakeable


def vendor(bakeable: "Bakeable"):
    """Vendor the plugins with the bakeable._plugin_factory"""

    @bakeable._plugin_factory.register
    class PluginFg:
        """Plugin: fg
        Running command in foreground
        Using sys.stdout and sys.stderr"""

        async def _feed(
            self: bakeable.CmdyResult,  # type: ignore
            poll_interval: float,
        ):
            """Try to feed stdout/stderr to sys.stdout/sys.stderr"""

            async def _feed_one(instream, outstream):
                try:
                    out = await curio.timeout_after(
                        poll_interval, instream.__anext__
                    )
                except curio.TaskTimeout:
                    pass
                except StopAsyncIteration:
                    return False
                else:
                    if self.holding.encoding:
                        outstream.write(out.decode(self.holding.encoding))
                    else:
                        outstream.buffer.write(out)
                    outstream.flush()
                return True

            out_live = err_live = True
            while out_live or err_live:
                if out_live:
                    out_live = await _feed_one(self.proc.stdout, sys.stdout)
                if err_live:
                    err_live = await _feed_one(self.proc.stderr, sys.stderr)

            if isinstance(self, bakeable.CmdyAsyncResult):
                await self.wait()

        async def _timeout_wrapper(
            self: bakeable.CmdyResult,  # type: ignore
            poll_interval: float,
        ):
            if self.holding.timeout:
                try:
                    await curio.timeout_after(
                        self.holding.timeout,
                        PluginFg._feed,
                        self,
                        poll_interval,
                    )
                except curio.TaskTimeout:
                    raise CmdyTimeoutError(
                        f"Timeout after {self.holding.timeout} seconds."
                    ) from None
            else:
                await PluginFg._feed(self, poll_interval)

        @bakeable._plugin_factory.hold_then("fg", final=True, hold_right=False)
        def foreground(
            self, stdin: bool = False, poll_interval: Union[bool, float] = 0.1
        ):
            """Running command in foreground
            Using sys.stdout and sys.stderr"""
            self.data.foreground.stdin = stdin
            self.data.foreground.poll_interval = poll_interval

            if not self._onhold():
                return self.run()
            return self

        @bakeable._plugin_factory.add_method(bakeable.CmdyHolding)
        def run(self, wait=None):
            """Run the command and bump stdout/stderr to sys'"""
            orig_run = self._original("run")

            if not self.data.get("foreground"):
                return orig_run(self, wait)

            if (
                (self.data.foreground.stdin and self.stdin != subprocess.PIPE)
                or self.stdout != subprocess.PIPE
                or self.stderr != subprocess.PIPE
            ):
                warnings.warn("Previous redirected pipe will be ignored.")

            # fileinput.input is good to use here
            # as it has fileno()
            self.stdin = (
                fileinput.input() if self.data.foreground.stdin else self.stdin
            )
            self.stdout = subprocess.PIPE
            self.stderr = subprocess.PIPE

            ret = orig_run(self, False)

            # we should handle timeout here, since we are not waiting
            curio.run(
                PluginFg._timeout_wrapper(
                    ret, self.data.foreground.poll_interval
                )
            )
            # we can't in self.wait() in curio.run, because there is
            # already a curio kernel running inside CmdyResult.wait()
            return (
                ret
                if isinstance(ret, bakeable.CmdyAsyncResult)
                else ret.wait()
            )

    return PluginFg()
