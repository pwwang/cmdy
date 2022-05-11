import inspect
from os import devnull
from functools import lru_cache
from subprocess import Popen

from diot import Diot
from simpleconf import ProfileConfig

_DEFAULT_CONFIG = Diot(
    {
        "async": False,
        "deform": lambda name: name.replace("_", "-"),
        "dupkey": False,
        "exe": None,
        "encoding": "utf-8",
        "okcode": [0],
        "prefix": "auto",
        "raise": True,
        "sep": " ",
        "shell": False,
        "sub": False,
        "timeout": 0,
    }
)

STDIN = -7
STDOUT = -2
STDERR = -8
DEVNULL = devnull

# Sometimes we may occasionally use envs instead env
POPEN_ARG_KEYS = inspect.getfullargspec(Popen).args + ["envs"]


@lru_cache()
def get_config() -> Diot:
    return ProfileConfig.load(
        {"default": _DEFAULT_CONFIG},
        "~/.cmdy.toml",
        "./.cmdy.toml",
        "CMDY.osenv",
        ignore_nonexist=True,
    )
