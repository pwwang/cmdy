from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from collections import namedtuple
from typing import TYPE_CHECKING, Callable, List, Tuple

from .version import __version__

if TYPE_CHECKING:
    from .core import CmdyProc

PluginReturnType = bool | None
PluginType = namedtuple("PluginType", ["name", "order", "func"])
PLUGINS: List[PluginType] = []


def register_plugin(name: str, order: int = 0) -> Callable:
    def wrapper(func):
        PLUGINS.append(PluginType(name, order, func))
        return func
    return wrapper


@register_plugin("default", order=99)
def default_plugin(proc: CmdyProc):
    if proc.proc:
        # allow proc to be created by other plugins
        return

    proc.logger.debug("Calling default plugin")
    pipes = {
        "STDOUT": subprocess.STDOUT,
        "PIPE": subprocess.PIPE,
        "DEVNULL": subprocess.DEVNULL,
    }
    popen_args = proc.popen_args.copy()
    popen_args.setdefault("stdin", subprocess.PIPE)
    popen_args.setdefault("stdout", subprocess.PIPE)
    popen_args.setdefault("stderr", subprocess.PIPE)
    if popen_args["stdin"] in pipes:
        popen_args["stdin"] = pipes[popen_args["stdin"]]
    if popen_args["stdout"] in pipes:
        popen_args["stdout"] = pipes[popen_args["stdout"]]
    if popen_args["stderr"] in pipes:
        popen_args["stderr"] = pipes[popen_args["stderr"]]

    file_pipe = False
    if isinstance(popen_args["stdin"], (str, Path)):
        popen_args["stdin"] = open(popen_args["stdin"], "r")
        file_pipe = True
    if isinstance(popen_args["stdout"], (str, Path)):
        flag = (
            "a"
            if (
                isinstance(popen_args["stdout"], str)
                and popen_args["stdout"].startswith(">>")
            )
            else "w"
        )
        popen_args["stdout"] = open(popen_args["stdout"], flag)
        file_pipe = True
    if isinstance(popen_args["stderr"], (str, Path)):
        flag = (
            "a"
            if (
                isinstance(popen_args["stdout"], str)
                and popen_args["stdout"].startswith(">>")
            )
            else "w"
        )
        popen_args["stderr"] = open(popen_args["stderr"], flag)
        file_pipe = True
    if file_pipe:
        popen_args.setdefault("close_fds", True)

    print(sys.stdout)
    proc.logger.debug(f"popen_args: ")
    for key, val in popen_args.items():
        proc.logger.debug(f"  {key}: {val}")
    proc.proc = subprocess.Popen(proc.cmds, **popen_args)


@register_plugin("async")
def async_plugin(proc: CmdyProc):
    if not proc.config.get("async"):
        return

    proc.logger.debug("Calling async plugin")
    pipes = {
        "STDOUT": asyncio.subprocess.STDOUT,
        "PIPE": asyncio.subprocess.PIPE,
        "DEVNULL": asyncio.subprocess.DEVNULL,
    }
    popen_args = proc.popen_args.copy()
    popen_args.setdefault("stdin", asyncio.subprocess.PIPE)
    popen_args.setdefault("stdout", asyncio.subprocess.PIPE)
    popen_args.setdefault("stderr", asyncio.subprocess.PIPE)
    if popen_args["stdin"] in pipes:
        popen_args["stdin"] = pipes[popen_args["stdin"]]
    if popen_args["stdout"] in pipes:
        popen_args["stdout"] = pipes[popen_args["stdout"]]
    if popen_args["stderr"] in pipes:
        popen_args["stderr"] = pipes[popen_args["stderr"]]

    proc.logger.debug(f"popen_args: ")
    for key, val in popen_args.items():
        proc.logger.debug(f"  {key}: {val}")
    proc.proc = asyncio.create_subprocess_exec(*proc.cmds, **popen_args)


@register_plugin("hold", order=-99)
def hold_plugin(proc: CmdyProc):
    if not proc.config.get("hold"):
        return

    proc.logger.debug("Calling hold plugin")
    if proc.proc:
        raise RuntimeError("Process already created")

    return False


@register_plugin("fg")
def fg_plugin(proc: CmdyProc):
    if not proc.config.get("fg"):
        return

    if (
        proc.popen_args.get("stdin")
        or proc.popen_args.get("stdout")
        or proc.popen_args.get("stderr")
    ):
        raise ValueError(
            "fg=True is not compatible with _stdin/_stdout/_stderr"
        )

    proc.logger.debug("Calling fg plugin")
    proc.popen_args["stdin"] = sys.stdin
    proc.popen_args["stdout"] = sys.stdout
    proc.popen_args["stderr"] = sys.stderr


@register_plugin("iter", order=98)
def iter_plugin(proc: CmdyProc):
    if not proc.config.get("iter"):
        return

    iter_which = proc.config.get("iter", "stdout")
    if iter_which is True:
        iter_which = "stdout"

    if (
        (iter_which in ("stdout", "both") and proc.popen_args.get("stdout"))
        or (iter_which == "stderr" and proc.popen_args.get("stderr"))
    ):
        raise ValueError(
            "iter=True/stdout/stderr/both is not compatible with "
            "_stdout/_stderr"
        )

    proc.logger.debug("Calling iter plugin")
    if iter_which == "stdout":
        proc.popen_args["stdout"] = "PIPE"
        proc._iterable = lambda: proc.proc.stdout
    elif iter_which == "stderr":
        proc.popen_args["stderr"] = "PIPE"
        proc._iterable = lambda: proc.proc.stderr
    elif iter_which == "both":
        proc.popen_args["stdout"] = "PIPE"
        proc.popen_args["stderr"] = "STDOUT"
        proc._iterable = lambda: proc.proc.stdout
    else:
        raise ValueError(
            f"Invalid _iter: {iter_which}, must be True/stdout/stderr/both"
        )


def call_plugins(
    proc: CmdyProc,
    plugins: List[PluginType] | None = None,
    break_on_false: bool = True,
) -> Tuple[List[PluginReturnType], List[PluginType]]:
    if plugins is None:
        plugins = PLUGINS

    out = []
    uncalled = []
    broken = False
    for plugin in sorted(plugins, key=lambda x: x.order):
        if not broken:
            o = plugin.func(proc)
            out.append(o)
            if o is False and break_on_false:
                broken = True
        elif broken:
            uncalled.append(plugin)

    return out, uncalled
