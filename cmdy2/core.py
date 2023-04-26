from __future__ import annotations

import asyncio
import logging
import shlex
import subprocess
from typing import Any, Callable, List, Mapping

from .plugins import call_plugins


def transform_kw_cmds(
    kwcmds: Mapping[str, Any],
    prefix: str,
    sep: str,
    transform_kw: Callable[[str, Any], str | List[str]] | None,
) -> List[str]:
    """Transform keyword commands"""
    if not transform_kw:
        def transform_kw(key: str, value: Any) -> str | List[str]:
            nonlocal prefix
            nonlocal sep
            if prefix == "auto":
                prefix = "--" if len(key) > 1 else "-"
            if sep == "auto":
                sep = "=" if len(key) > 1 else " "

            if value is True:
                return f"{prefix}{key}"
            if value is False:
                return []

            if sep != " ":
                return f"{prefix}{key}{sep}{value}"
            return [f"{prefix}{key}", str(value)]

    cmds = []
    for key, value in kwcmds.items():
        transformed = transform_kw(key, value)
        if not isinstance(transformed, list):
            transformed = [transformed]
        cmds.extend(transformed)
    return cmds


class Cmdy:

    def __init__(
        self,
        exe: str | List[str],
        config: Mapping[str, Any],
        logger: logging.Logger,
    ) -> None:
        self.cmds = exe if isinstance(exe, list) else [exe]
        self.config = config
        self.logger = logger

    def __getattr__(self, name: str) -> Cmdy:
        return self.__class__(self.cmds + [name], self.config)

    def __repr__(self) -> str:
        return f"<Cmdy {' '.join(self.cmds)!r} @ {id(self):#x}>"

    def __call__(self, *args, **kwds) -> CmdyProc:
        cmds = self.cmds + [str(arg) for arg in args]
        # separate config and popen args
        config = {}
        popen_args = {}
        kwcmds = {}
        for key, val in self.config.items():
            if key in (
                "stdin",
                "stdout",
                "stderr",
                "cwd",
                "env",
                "encoding",
                "errors",
                "text",
                "universal_newlines",
                "bufsize",
                "close_fds",
            ):
                popen_args[key] = val
            elif key.startswith("popen_"):
                popen_args[key[6:]] = val
            else:
                config[key] = val

        for key, value in kwds.items():
            if key in (
                "_stdin",
                "_stdout",
                "_stderr",
                "_cwd",
                "_env",
                "_encoding",
                "_errors",
                "_text",
                "_universal_newlines",
                "_bufsize",
                "_close_fds",
            ):
                popen_args[key[1:]] = value
            elif key.startswith("_p_"):
                popen_args[key[3:]] = value
            elif key.startswith("_"):
                config[key[1:]] = value
            else:
                kwcmds[key] = value

        prefix = config.pop("prefix", "auto")
        sep = config.pop("sep", "auto")
        transform_kw = config.pop("transform_kw", None)
        kwcmds = transform_kw_cmds(kwcmds, prefix, sep, transform_kw)
        self.logger.setLevel(config.get("loglevel", logging.INFO))
        cmdy_proc = CmdyProc(cmds + kwcmds, config, popen_args, self.logger)
        if config.get("async"):
            async def await_proc():
                if asyncio.iscoroutine(cmdy_proc.proc):
                    cmdy_proc.proc = await cmdy_proc.proc
                return cmdy_proc
            return await_proc()

        return cmdy_proc


class CmdyProc:

    def __init__(
        self,
        cmds: List[str],
        config: Mapping[str, Any],
        popen_args: Mapping[str, Any],
        logger: logging.Logger,
    ) -> None:
        self.cmds = cmds
        self.strcmd = shlex.join(cmds)
        self.config = config
        self.popen_args = popen_args
        self.proc = None
        self.logger = logger
        self._iter = None
        self._ror = None
        self._gt = None
        self._lt = None
        self._uncalled_plugins = None

        out, self._uncalled_plugins = call_plugins(self)
        if out and out[-1] is False:
            self.logger.debug("Creating proc is held by plugins")
            return

        for o in out:
            if (
                isinstance(out, subprocess.Popen)
                or asyncio.iscoroutine(out)
            ):
                self.proc = o

        if self.config.get("async"):
            self.start = self._start_async
        else:
            self.start = self._start_sync

    async def _start_async(self) -> None:
        self.logger.debug("Resuming proc creation")
        # Call the plugins that are not called yet
        call_plugins(self, self._uncalled_plugins, False)
        self.proc = await self.proc
        return self

    def _start_sync(self) -> None:
        self.logger.debug("Resuming proc creation")
        # Call the plugins that are not called yet
        call_plugins(self, self._uncalled_plugins, False)
        return self

    def __repr__(self) -> str:
        if not self.config.get("async") and self.proc and self.stdout:
            stdout = self.stdout.read()
            if isinstance(stdout, bytes):
                stdout = stdout.decode()
            return (
                f"<Cmdy {' '.join(self.cmds)!r} @ "
                f"{id(self):#x} (pid={self.proc.pid})>\n"
                f"{stdout}"
            )

        if self.config.get("async"):
            return f"<Cmdy {' '.join(self.cmds)!r} @ {id(self):#x} (async)>"

        if self.proc:
            return (
                f"<Cmdy {' '.join(self.cmds)!r} @ "
                f"{id(self):#x} (pid={self.proc.pid})>"
            )

        return f"<Cmdy {' '.join(self.cmds)!r} @ {id(self):#x} (onhold)>"

    def __getattr__(self, name: str) -> Any:
        if name == "start":
            if self.config.get("async"):
                return self._start_async
            return self._start_sync

        if self.proc is None:
            raise RuntimeError("Process not created yet")

        return getattr(self.proc, name)

    def __iter__(self) -> Any:
        if self._iter is None:
            raise TypeError(
                f"{self.__class__.__name__!r} object is not iterable"
            )

        return self._iter()

    def __aiter__(self) -> Any:
        if self._iter is None:
            raise TypeError(
                f"{self.__class__.__name__!r} object is not iterable"
            )

        return self._iter()

    def __ror__(self, __value: Any) -> CmdyProc:

        return self._ror(__value)