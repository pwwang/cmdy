"""Utilities for cmdy"""
import inspect
import warnings
from copy import copy
from functools import wraps
from os import environ
from typing import TYPE_CHECKING, List, Tuple, Union

import curio
import executing
from diot import Diot
from simpleconf import ProfileConfig

from .cmdy_defaults import POPEN_ARG_KEYS
from .cmdy_exceptions import CmdyReturnCodeError

if TYPE_CHECKING:
    from .cmdy_result import CmdyAsyncResult


async def raise_return_code_error(aresult: "CmdyAsyncResult"):
    """Raise CmdyReturnCodeError from CmdyAsyncResult
    Compose a fake CmdyResult for CmdyReturnCodeError
    """
    # this should be
    result = Diot(
        rc=aresult._rc,
        pid=aresult.pid,
        cmd=aresult.cmd,
        piped_strcmds=getattr(aresult, "piped_strcmds", None),
        holding=Diot(okcode=aresult.holding.okcode),
        _stdout_str=(await aresult.stdout.read() if aresult.stdout else ""),
        _stderr_str=(await aresult.stderr.read() if aresult.stderr else ""),
        stdout=aresult.stdout,
        stderr=aresult.stderr,
    )

    raise CmdyReturnCodeError(result)


class SyncStreamFromAsync:
    """Take an async iterable into a sync iterable
    We use curio.run to fetch next record each time
    A StopIteration raised when a StopAsyncIteration raises
    for the async iterable
    """

    def __init__(self, astream: curio.io.FileStream, encoding: str = None):
        self.astream = astream
        self.encoding = encoding

    async def _fetch_next(self, timeout: float = None):
        await self.astream.flush()
        if timeout:
            ret = await curio.timeout_after(timeout, self.astream.__anext__)
        else:
            ret = await self.astream.__anext__()
        return ret.decode(self.encoding) if self.encoding else ret

    def next(self, timeout: float = None):
        """Fetch the next record within give timeout
        If nothing produced after the timeout, returns empty str or bytes
        """
        try:
            return curio.run(self._fetch_next(timeout))
        except StopAsyncIteration:
            raise StopIteration() from None
        except curio.TaskTimeout:
            return "" if self.encoding else b""

    def __next__(self):
        return self.next()  # pylint: disable=not-callable

    def __iter__(self):
        return self

    def dump(self):
        """Dump all records as a string or bytes"""
        return ("" if self.encoding else b"").join(self)


def property_called_as_method(caller=1):
    """Tell if a property is called by a method way"""
    frame = inspect.stack()[caller + 1].frame
    source = executing.Source.executing(frame)
    node = source.node
    try:

        return node.parent.func is node
    except AttributeError:
        return False


def property_or_method(func):
    """Make a class property also available to be called as a method"""

    @wraps(func)
    def wrapper(self):
        if property_called_as_method():

            @wraps(func)
            def func_wrapper(*args, **kwargs):
                return func(self, *args, **kwargs)

            return func_wrapper
        return func(self)

    return wrapper


def compose_arg_segment(cmd_args: dict, config: Diot) -> List[str]:
    """Compose a list of command-line arguments from the cmd_args
    by given argument composing configs, including prefix, sep and dupkey

    Note that `cmd_args` should not be reused, it will be changed in this
    function

    Examples:
        >>> compose_arg_segment({'a': 1, 'ab': 2}, {})
        >>> # ['-a', '1', '--ab', '2']
        >>> compose_arg_segment({'a': 1, 'ab': 2}, {'prefix': '--'})
        >>> # ['--a', '1', '--ab', '2']
        >>> compose_arg_segment({'a': 1, 'ab': 2}, {'sep': '='})
        >>> # ['-a=1', '--ab=2']
        >>> compose_arg_segment({'a': True, 'ab': 2}, {})
        >>> # ['-a', '--ab', '2']
        >>> compose_arg_segment({'a': False, 'ab': 2}, {})
        >>> # ['--ab', '2']
        >>> compose_arg_segment({'a': [1, 2]}, {})
        >>> # ['-a', '1', '2']
        >>> compose_arg_segment({'a': [1, 2]}, {'dupkey': True})
        >>> # ['-a', '1', '-a', '2']
        >>> compose_arg_segment({'_': [3, 4], '': [1, 2]}, {})
        >>> # ['1', '2', '3', '4']

    Args:
        cmd_args (dict): The keyword arguments for the command
        config (Diot): The configs for composing the arguments

    Returns:
        list: The composed arguments
    """
    ret: List[str] = []
    leadings = cmd_args.pop("", [])
    ret.extend(leadings if isinstance(leadings, (tuple, list)) else [leadings])

    positionals = cmd_args.pop("_", [])
    positionals = (
        positionals
        if isinstance(positionals, (tuple, list))
        else [positionals]
    )

    for key, value in cmd_args.items():
        if callable(config.deform):
            key = config.deform(key)
        prefix = (
            config.prefix
            if config.prefix != "auto"
            else "-"
            if len(key) == 1  # '' has been pop'ed
            else "--"
        )
        sep = (
            config.sep
            if config.sep != "auto"
            else " "
            if len(key) == 1
            else "="
        )
        if not isinstance(value, list):
            value = [value]

        for i, val in enumerate(value):
            if val is False:
                continue
            if sep == " ":
                if i == 0 or config.dupkey:
                    ret.append(f"{prefix}{key}")
                if val is not True:
                    ret.append(val)
            else:
                if i == 0 or config.dupkey:
                    ret.append(
                        f"{prefix}{key}"
                        + ("" if val is True else sep + str(val))
                    )
                elif val is not True:
                    ret.append(val)

    ret.extend(positionals)

    return [str(item) for item in ret]


def normalize_config(config: Diot):
    """Normalize shell and okcode to list"""
    if "okcode" in config:
        if isinstance(config.okcode, str):
            config.okcode = [okc.strip() for okc in config.okcode.split(",")]
        if not isinstance(config.okcode, list):
            config.okcode = [config.okcode]
        config.okcode = [int(okc) for okc in config.okcode]

    if "shell" in config and config.shell:
        if config.shell is True:
            config.shell = ["/bin/bash", "-c"]
        if not isinstance(config.shell, list):
            config.shell = [config.shell, "-c"]
        elif len(config.shell) == 1:
            config.shell.append("-c")


def fix_popen_config(popen_config: Diot):
    """Fix when env wrongly passed as envs.
    Send the whole `os.environ` instead of a piece of it given by
    popen_config.env
    And also raise warnings if configs should not go with popen but rather
    cmdy.
    """
    if "envs" in popen_config:
        if "env" in popen_config:
            warnings.warn(
                "Both envs and env specified in popen args, envs will"
                "be ignored"
            )
            del popen_config["envs"]
        else:
            popen_config["env"] = popen_config.pop("envs")

    if "env" in popen_config:
        normalized_env = {}
        for key, value in popen_config.env.items():
            if isinstance(value, bool):
                value = int(value)
            normalized_env[key] = str(value)

        envs = environ.copy()
        envs.update(normalized_env)

        popen_config.env = envs

    for pipe in ("stdin", "stdout", "stderr"):
        if pipe in popen_config:
            warnings.warn(
                "Motifying pipes are not allowed. " "Values will be ignored"
            )
            del popen_config[pipe]


def parse_single_kwarg(
    kwarg: dict, is_root: bool, global_config: dict
) -> "Tuple[dict, dict, dict]":
    """Parse a single kwarg that passed in `cmdy.ls({...}, ...)`
    as non-keyword arguments. Since some argument-related configurations
    can be passed in that single kwarg.
    This allows different configurations of the arguments passed to execute
    the program.

    Here we want to support the old style config item specification
    Tranditionally, we are using arguments prefixed with '_' to indicate
    that this is a config (either cmdy or popen) item rather than an argument
    that should be passed to the command.

    To do that, we first scan if there are any arguments prefixed with
    'cmdy_' or 'popen_' explictly passed. If so, we store them, and treat
    any argument starting with '_' and having the same name as an argument
    that should be passed to the command.

    For example: `{'_raise': True, 'cmdy_raise': True}` will result in
    `--_raise` as argument passing to command. To avoid that, using
    explict config name instead: `{'cmdy_raise': True}`.
    If only `{'_raise': True}` passed, it will be treated as a config item.

    A note for popen configs and cmdy configs that having the same name.
    Warnings will be give, if `encoding` and `shell` is trying to specified as
    popen configs. The reasons are:

    1. `curio.subprocess` is not handling any encoding stuff. It always
    produces bytes. `cmdy` wraps it and gives it ability to decode the bytes.
    2. `shell` is always set to `False` when the command passed to
    `curio.subprocess`. To run a command with `shell = True`, `cmdy` wraps it
    with `bash -c` or any shell that you passed to `cmdy_shell`

    Examples:
        >>> parse_single_kwarg({'a': 1, 'boy': 2, 'cmdy_prefix': '--'})
        >>> # {'a': 1, 'boy': 2}, {'prefix': '--'}, None

    Args:
        kwarg (dict): The single kwarg argument
        is_root (bool): Whether the kwarg is from the root
            (the `kwargs` from `cmdy.ls(*args, **kwargs)` directly
            For non-root kwarg, only 3 configuration items are allowed:
            `cmdy_prefix`, `cmdy_sep` and `cmdy_dupkey` and NO `popen` args
            are allowed.
        global_config (dict): The global configuration for composing the
            command-line arguments. We should have all config items
            in this global config.

    Returns:
        tuple(dict, dict, dict):
            A dict contains arguments for command only,
            local_config if not is_root else the updated global_config and,
            None if not is_root else the popen arguments

    Raises:
        ValueError: If extra arguments other than those 3 or popen
            configs are passed for non-root kwarg

    Warns:
        UserWarning: When `encoding` or `shell` passed as popen configs
    """
    # global_config = global_config.copy()

    # scan for configuration first
    local_config = Diot()
    popen_config = Diot()
    tmp_kwargs = {}
    for key, val in kwarg.items():
        if key.startswith("cmdy_"):
            local_config[key[5:]] = val
        elif key.startswith("popen_"):
            popen_config[key[6:]] = val
        else:
            tmp_kwargs[key] = val

    # kwargs without any config
    pure_cmd_kwargs = {}
    # further scan for config item starting with '_'
    for key, val in tmp_kwargs.items():
        if key.startswith("_"):
            key = key[1:]
            if key in global_config and key not in local_config:
                local_config[key] = val
            elif key in POPEN_ARG_KEYS and key not in popen_config:
                popen_config[key] = val
            else:
                pure_cmd_kwargs["_" + key] = val
        else:
            pure_cmd_kwargs[key] = val

    del tmp_kwargs

    if not is_root:
        if popen_config or any(
            key in local_config
            for key in global_config
            if key not in ("sep", "prefix", "dupkey")
        ):
            raise ValueError("Extra configs passed in argument segment.")
        return (pure_cmd_kwargs, local_config, None)

    if "shell" in popen_config:
        local_config.shell = popen_config.pop("shell")
        warnings.warn("To change the shell mode, use cmdy_shell instead.")

    if "encoding" in popen_config:
        local_config.encoding = popen_config.pop("encoding")
        warnings.warn("Please use cmdy_encoding instead of popen_encoding.")

    # global_config.update(local_config)

    return (pure_cmd_kwargs, local_config, popen_config)


def parse_args(
    name: str,
    args: tuple,
    kwargs: dict,
    # we have to pass the CMDY_CONFIG and _CMDY_BAKED_ARGS
    # here for baking purposes.
    # If we don't it will always use the original module's
    config: Diot,
    baked_args: Diot,
) -> Diot:
    """Get parse whatever passed to `cmdy.command(...)`

    Examples:
        >>> parse_args("a", "--l=a", {'x': True}, cmdy_shell=True,
                       popen_envs={...})
        >>> # ["a", "--l=a", "-x"], {"shell": True}, {"envs": {...}}

    Args:
        args (tuple): The arugments passed to `cmdy.ls(...)`
        kwargs (dict): The kwargs passed to `cmdy.ls(...)`
        cmdy_config (Config): CMDY_CONFIG from main module, passing for
            module baking purposes
        baked_args (Diot): _CMDY_BAKED_ARGS from main module, passing for
            module baking purposes

    Returns:
        tuple(list, Diot, Diot):
            The ready arguments to put to command,
            The cmdy configurations,
            The arguments will be passed to `Popen`
    """
    ret_args: list = []
    ret_kwargs: dict = {}

    # without cmdy_ prefix
    # full configs
    global_config = ProfileConfig.use_profile(config, "default", copy=True)
    # configs that only specified
    if ProfileConfig.has_profile(config, name):
        nondefault_config = ProfileConfig.use_profile(
            config,
            name,
            base=None,
            copy=True,
        )
    else:
        nondefault_config = Diot()

    ret_kwargs, baked_config, baked_popen_args = parse_single_kwarg(
        baked_args, is_root=True, global_config=global_config
    )

    global_config.update(baked_config)
    nondefault_config.update(baked_config)

    pure_cmd_kwargs, local_config, popen_config = parse_single_kwarg(
        kwargs, is_root=True, global_config=global_config
    )

    ret_kwargs.update(pure_cmd_kwargs)

    nondefault_config.update(local_config)
    global_config.update(local_config)

    baked_popen_args.update(popen_config)
    popen_config = baked_popen_args

    for arg in args:
        if isinstance(arg, dict):
            pure_cmd_kwargs_seg, local_config, _ = parse_single_kwarg(
                arg, is_root=False, global_config=global_config
            )
            if any(key in pure_cmd_kwargs for key in pure_cmd_kwargs_seg):
                warnings.warn(
                    "Argument has been specified "
                    "in both *args and **kwargs. "
                    "The one in *args will be ignored.",
                    UserWarning,
                )
                continue
            lconfig = global_config.copy()
            lconfig.update(local_config)
            ret_args.extend(compose_arg_segment(pure_cmd_kwargs_seg, lconfig))
        else:
            ret_args.append(str(arg))

    # ret_args.extend(compose_arg_segment(
    #     pure_cmd_kwargs, global_config
    # ))

    normalize_config(nondefault_config)
    fix_popen_config(popen_config)
    return Diot(
        args=ret_args,
        kwargs=ret_kwargs,
        config=nondefault_config,
        popen=popen_config,
    )


def compose_cmd(
    args: list,
    kwargs: dict,
    config: Diot,
    shell: Union[list, bool],
) -> list:
    """Compose the command for Popen.
    If shell is False, args will be directly returned. Otherwise
    args will be joined and wrapped by the shell

    Args:
        args (list): The ready args, including the executable
        kwargs (dict): The keyword arguments
        shell (str|bool): Whether we should run the whold command,
            or the path of the shell to wrap the command
            If it is True, '/bin/bash' will be used.
            Note that this is different from `Popen` behavior, which uses
            `/bin/sh` by default

    Returns:
        list: The args if shell if False, otherwise shell wrapped command
    """
    command = args[:]
    command.extend(compose_arg_segment(kwargs, config))

    if not shell:
        return command

    return shell + [" ".join(command)]  # type: ignore


def new_class(
    base: Union[type, Tuple],
    name: str = None,
    data: dict = None,
) -> type:
    """Copy the base class and copy its properties

    Subclass the base class, the property values is not copied,
    but just reference to the original one.

    Examples:
        >>> class A:
        >>>     a = [1, 2]
        >>>
        >>> class B(A):
        >>>     pass
        >>>
        >>> B.a[0] = 3
        >>> A.a  # [3, 2]
        >>>
        >>> C = copy_class(A, "C")
        >>> C.a[0] = 4
        >>> A.a  # [3, 2]
    """
    if isinstance(base, type):
        base = (base,)
    name = name or base[-1].__name__
    data = data or {}
    basedata = lambda b: {  # noqa: E731
        key: copy(val)
        for key, val in b.__dict__.items()
        if not key.startswith("__") and not callable(val)
    }
    classdata = {}
    for b in base:
        classdata.update(basedata(b))
    classdata.update(data)
    return type(name, base, classdata)
