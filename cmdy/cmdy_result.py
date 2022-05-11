import inspect
from shlex import quote

import curio
from curio import subprocess
from diot import Diot

from .cmdy_defaults import STDOUT
from .cmdy_exceptions import CmdyTimeoutError, CmdyReturnCodeError
from .cmdy_utils import SyncStreamFromAsync, raise_return_code_error


class CmdyResult:

    """Sync version of result"""

    def __init__(self, proc, holding):
        self.proc = proc
        self.holding = holding
        self.did = self.curr = ""
        self.will = holding.will
        self._stdout = None
        self._stderr = None
        self.data = Diot()
        self._rc = None

    def __repr__(self):
        return f"<CmdyResult: {self.cmd}>"

    @property
    def rc(self):
        """Get the return code"""
        if self._rc is not None:
            return self._rc
        self.wait()
        return self._rc

    @property
    def pid(self):
        """Get the pid of the process"""
        return self.proc.pid

    @property
    def cmd(self):
        """Get the stringified command"""
        return self.holding.cmd

    @property
    def strcmd(self):
        """Get the stringified cmd"""
        return " ".join(quote(cmdpart) for cmdpart in self.cmd)

    def wait(self):
        """Wait until command is done"""
        timeout = self.holding.timeout
        try:
            if timeout:
                self._rc = curio.run(
                    curio.timeout_after(timeout, self.proc.wait)
                )
            else:
                self._rc = curio.run(self.proc.wait())
        except curio.TaskTimeout:
            self.proc.kill()
            raise CmdyTimeoutError(
                f"Timeout after {self.holding.timeout} seconds."
            ) from None
        else:
            if self._rc not in self.holding.okcode and self.holding.raise_:
                raise CmdyReturnCodeError(self)
            return self
        finally:
            self._close_fds()

    def _close_fds(self):
        if not self.holding.should_close_fds:
            return
        for filed in self.holding.should_close_fds.values():
            if filed:
                filed.close()

    @property
    def stdout(self):
        """The stdout of the command"""
        if self.holding.stdout != subprocess.PIPE:
            # redirected, we are unable to fetch the stdout
            return None

        if self._stdout is not None:
            return self._stdout

        self._stdout = SyncStreamFromAsync(
            self.proc.stdout, encoding=self.holding.encoding
        ).dump()
        return self._stdout

    @property
    def stderr(self):
        """The stderr of the command"""
        if self.holding.stderr != subprocess.PIPE:
            # redirected, we are unable to fetch the stdout
            return None

        if self._stderr is not None:
            return self._stderr
        self._stderr = SyncStreamFromAsync(
            self.proc.stderr, encoding=self.holding.encoding
        ).dump()
        return self._stderr


class CmdyAsyncResult:
    """Asyncronous result"""

    def __repr__(self):
        return f"<CmdyAsyncResult: {self.cmd}>"

    async def _close_fds(self):
        if not self.holding.should_close_fds:
            return
        try:
            for filed in self.holding.should_close_fds.values():
                if filed:
                    coro = filed.close()
                    if inspect.iscoroutine(coro):
                        await coro  # pragma: no cover
        except AttributeError:  # pragma: no cover
            pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        which = self.data.get("iter", {}).get("which", STDOUT)
        stream = self.stdout if which == STDOUT else self.stderr
        try:
            line = await stream.__anext__()
        except StopAsyncIteration:
            await self.wait()
            raise
        if self.holding.encoding:
            line = line.decode(self.holding.encoding)
        return line

    async def wait(self):
        timeout = self.holding.timeout

        try:
            if timeout:
                self._rc = await curio.timeout_after(timeout, self.proc.wait)
            else:
                self._rc = await self.proc.wait()
        except curio.TaskTimeout:
            self.proc.kill()
            raise CmdyTimeoutError(
                "Timeout after " f"{self.holding.timeout} seconds."
            ) from None
        else:
            if self._rc not in self.holding.okcode and self.holding.raise_:
                await raise_return_code_error(self)
            return self
        finally:
            await self._close_fds()

    @property
    async def rc(self):
        if self._rc is not None:
            return self._rc
        await self.wait()
        return self._rc

    @property
    def stdout(self):
        return self.proc.stdout

    @property
    def stderr(self):
        return self.proc.stderr
