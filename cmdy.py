"""A handy package to run command from python"""
# pylint: disable=too-many-lines
# ----------------------------------------------------------
# Naming rules to save the names for the uses of
# >>> from cmdy import ...
#
# 1. Anything that is imported will be prefixed with '_'
# 2. Any constants to be exported will be prefixed with 'CMDY_'
# 3. Any functions to be exported will be prefixed with 'cmdy_'
# 4. 3 also includes plugin hooks
# ----------------------------------------------------------
import sys as _sys
import fileinput as _fileinput
from os import devnull as _devnull
from functools import wraps as _wraps
from threading import Event as _Event
from shlex import quote as _quote
import warnings as _warnings
import inspect as _inspect
from diot import Diot as _Diot
from modkit import modkit as _modkit
from simpleconf import Config as _Config
import curio as _curio
from curio import subprocess as _subprocess
from varname import will as _will

# We cannot define the variables that need to be baked
# in submodules, because we don't want to deepcopy the
# whole module.
_CMDY_DEFAULT_CONFIG = _Diot(
    cmdy_async=False,
    cmdy_exe=None,
    cmdy_dupkey=False,
    cmdy_okcode=0,
    cmdy_prefix='auto',
    cmdy_raise=True,
    cmdy_sep=' ',
    cmdy_shell=False,
    cmdy_encoding='utf-8',
    cmdy_timeout=0
)

CMDY_CONFIG = _Config()
CMDY_CONFIG._load(
    dict(default=_CMDY_DEFAULT_CONFIG),
    '~/.cmdy.toml',
    './.cmdy.toml',
    'CMDY.osenv'
)

_CMDY_BAKED_ARGS = _Diot()
_CMDY_EVENT = _Event()

# These are naming exceptions for convenience
STDIN = -7
STDOUT = -2
STDERR = -8
# or '/dev/null'?
DEVNULL = _devnull

# The actions that will put left side on hold
# For example: cmdy.ls().h()
# will put cmdy.ls() on hold
_CMDY_HOLDING_LEFT = ['a', 'async_', 'h', 'hold']
# The actions that will put right side on hold
# For example: cmdy.ls().r(STDERR).fg() > DEVNULL
# If "r" is in _CMDY_HOLDING_RIGHT, then fg() will be on hold
# The command will run by ">"
_CMDY_HOLDING_RIGHT = []
_CMDY_HOLDING_FINALS = []
_CMDY_RESULT_FINALS = []

class CmdyBakingError(Exception):
    """Baking from non-keyword arguments"""

class CmdyActionError(Exception):
    """Wrong actions taken"""

class CmdyTimeoutError(Exception):
    """Timeout running command"""

class CmdyExecNotFoundError(Exception):
    """Unable to find the executable"""

class CmdyReturnCodeError(Exception):
    """Unexpected return code"""

    @staticmethod
    def _out_nowait(result, which):
        if which == STDOUT and getattr(result, '_stdout_str', None) is not None:
            return result._stdout_str.splitlines()
        if which == STDERR and getattr(result, '_stderr_str', None) is not None:
            return result._stderr_str.splitlines()

        out = result.stdout if which == STDOUT else result.stderr
        if isinstance(out, (str, bytes)):
            return out.splitlines()

        return list(out)

    def __init__(self, result):
        if isinstance(result, (_Diot, CmdyResult)):
            msgs = [f'Unexpected RETURN CODE {result.rc}, '
                    f'expecting: {result.holding.okcode}',
                    '',
                    f'  [   PID] {result.pid}',
                    '',
                    '  [   CMD] '
                    f'{getattr(result, "piped_strcmds", result.cmd)}',
                    '']

            if result.stdout is None:
                msgs.append('  [STDOUT] <NA / ITERATED / REDIRECTED>')
                msgs.append('')
            else:
                outs = CmdyReturnCodeError._out_nowait(result, STDOUT) or ['']
                msgs.append(f'  [STDOUT] {outs.pop().rstrip()}')
                msgs.extend(f'           {out}' for out in outs[:31])
                if len(outs) > 31:
                    msgs.append(f'           [{len(outs)-31} lines hidden.]')
                msgs.append('')

            if result.stderr is None:
                msgs.append('  [STDERR] <NA / ITERATED / REDIRECTED>')
                msgs.append('')
            else:
                errs = CmdyReturnCodeError._out_nowait(result, STDERR) or ['']
                msgs.append(f'  [STDERR] {errs.pop().rstrip()}')
                msgs.extend(f'           {err}' for err in errs[:31])
                if len(errs) > 31:
                    msgs.append(f'           [{len(errs)-31} lines hidden.]')
                msgs.append('')
        else: # pragma: no cover
            msgs = [str(result)]
        super().__init__('\n'.join(msgs))

async def _cmdy_raise_return_code_error(aresult):
    """Raise CmdyReturnCodeError from CmdyAsyncResult
    Compose a fake CmdyResult for CmdyReturnCodeError
    """
    # this should be
    result = _Diot(rc=aresult._rc,
                   pid=aresult.pid,
                   cmd=aresult.cmd,
                   piped_strcmds=getattr(aresult, 'piped_strcmds', None),
                   holding=_Diot(okcode=aresult.holding.okcode),
                   _stdout_str=(await aresult.stdout.read()
                                if aresult.stdout else ''),
                   _stderr_str=(await aresult.stderr.read()
                                if aresult.stderr else ''),
                   stdout=aresult.stdout,
                   stderr=aresult.stderr)

    raise CmdyReturnCodeError(result)

# not for external use
class _CmdySyncStreamFromAsync:
    """Take an async iterable into a sync iterable
    We use _curio.run to fetch next record each time
    A StopIteration raised when a StopAsyncIteration raises
    for the async iterable
    """
    def __init__(self, astream: _curio.io.FileStream,
                 encoding: str = None):
        self.astream = astream
        self.encoding = encoding

    async def _fetch_next(self, timeout: float = None):
        await self.astream.flush()
        if timeout:
            ret = await _curio.timeout_after(timeout, self.astream.__anext__)
        else:
            ret = await self.astream.__anext__()
        return ret.decode(self.encoding) if self.encoding else ret

    def next(self, timeout: float = None):
        """Fetch the next record within give timeout
        If nothing produced after the timeout, returns empty str or bytes
        """
        try:
            return _curio.run(self._fetch_next(timeout))
        except StopAsyncIteration:
            raise StopIteration()
        except _curio.TaskTimeout:
            return '' if self.encoding else b''

    def __next__(self):
        return self.next()

    def __iter__(self):
        return self

    def dump(self):
        """Dump all records as a string or bytes"""
        return ('' if self.encoding else b'').join(self)

def _cmdy_parse_args(name: str, args: tuple, kwargs: dict):
    """Get parse whatever passed to cmdy.ls()

    Example:
        ```python
        parse_args("a", "--l=a", {'x': True}, cmdy_pipe=True,
                   popen_encoding='utf-8')
        # gives:
        # ["a", "--l=a"], {"x": True}, {"pipe": True}, {"encoding": 'utf-8'}
        ```

    Args:
        args (tuple): The arugments passed to `cmdy.ls(...)`
        kwargs (dict): The kwargs passed to `cmdy.ls(...)`
    """
    ret_args: list = []
    ret_kwargs: dict = {}
    ret_cfgargs: _Diot = _Diot()
    ret_popenargs: _Diot = _Diot()

    base_kwargs = CMDY_CONFIG._use(name, 'default', copy=True)
    base_kwargs.update(_CMDY_BAKED_ARGS)
    base_kwargs.update(kwargs)

    for key, val in base_kwargs.items():
        if key.startswith('popen_'):
            ret_popenargs[key[6:]] = val
        elif key.startswith('cmdy_'):
            ret_cfgargs[key[5:]] = val
        elif val is not False:
            ret_kwargs[key] = val

    for arg in args:
        if isinstance(arg, dict):
            for key, val in arg.items():
                if key in ret_kwargs:
                    _warnings.warn(f"Argument {key} has been specified "
                                   "in both *args and **kwargs. "
                                   "The one in *args will be ignored.",
                                   UserWarning)
                    continue
                if val is not False:
                    ret_kwargs[key] = val
        else:
            ret_args.append(str(arg))

    for pipe in ('stdin', 'stdout', 'stderr'):
        if pipe in ret_popenargs:
            _warnings.warn("Motifying pipes are not allowed. "
                           "Values will be ignored")
            del ret_popenargs[pipe]

    if 'encoding' in ret_popenargs:
        _warnings.warn("Please use cmdy_encoding instead of popen_encoding.")

    if 'shell' in ret_popenargs:
        _warnings.warn("To change the shell mode, use cmdy_shell instead.")
        del ret_popenargs.shell

    if isinstance(ret_cfgargs.okcode, str):
        ret_cfgargs.okcode = [okc.strip()
                              for okc in ret_cfgargs.okcode.split(',')]
    if not isinstance(ret_cfgargs.okcode, list):
        ret_cfgargs.okcode = [ret_cfgargs.okcode]
    ret_cfgargs.okcode = [int(okc) for okc in ret_cfgargs.okcode]

    if ret_cfgargs.shell:
        if ret_cfgargs.shell is True:
            ret_cfgargs.shell = ['/bin/bash', '-c']
        if not isinstance(ret_cfgargs.shell, list):
            ret_cfgargs.shell = [ret_cfgargs.shell, '-c']
        elif len(ret_cfgargs.shell) == 1:
            ret_cfgargs.shell.append('-c')

    return ret_args, ret_kwargs, ret_cfgargs, ret_popenargs

def _cmdy_compose_cmd(args: list, kwargs: dict, *,
                      shell: list, prefix: str,
                      sep: str, dupkey: bool) -> list:
    """Compose the command for Popen"""
    command = args[:]

    precedings = kwargs.pop('', [])
    command.extend(precedings if isinstance(precedings, list) else [precedings])

    positionals = kwargs.pop('_', [])

    for key, value in kwargs.items():
        pref = prefix if prefix != 'auto' else '-' if len(key) == 1 else '--'
        separator = sep if sep != 'auto' else ' ' if len(key) == 1 else '='
        if not isinstance(value, list):
            value = [value]

        for i, val in enumerate(value):
            if separator == ' ':
                if i == 0 or dupkey:
                    command.append(f'{pref}{key}')
                if val is not True:
                    command.append(str(val))
            else:
                if i == 0 or dupkey:
                    command.append(f'{pref}{key}{separator}{val}')
                elif val is not True:
                    command.append(str(val))

    if not isinstance(positionals, (tuple, list)):
        positionals = [positionals]

    command.extend(str(pos) for pos in positionals)

    if shell:
        return shell + [' '.join(command)]
    return command

class Cmdy:
    """Cmdy class
    It's just a bridge for doing cmdy.ls -> cmdy.ls()
    """

    def __init__(self, name: str,
                 args: list = None,
                 kwargs: dict = None,
                 cfgargs: _Diot = None,
                 popenargs: _Diot = None):
        """Initialize Cmdy object

        Args:
            name (str): The command name. (The `ls` in `cmdy.ls()`)
                This is the only required arguments. Other arguments below
                should be baking arguments, which will be used as base for
                futher command call.
            args (list): The non-keyword arguments, including subcommands
            kwargs (dict): The keyword arguments
            cfgargs (_Diot): The configuration arguments, starting with `cmdy_`
            popenargs (_Diot): The arguments for `subprocess.Popen`

        """
        self._name: str = name # should be not changed later on
        # cmdy.ls("/path/to")
        self._args: list = args or []
        # cmdy.ls(l="/path/to")
        self._kwargs: dict = kwargs or {}
        # cmdy.ls(cmdy_prefix="-", l=...)
        self._cfgargs: _Diot = cfgargs
        # cmdy.ls(cmdy_stdin="/dev/stdin")
        self._popenargs: _Diot = popenargs

    def __call__(self, *args, **kwargs):
        _args, _kwargs, _cfgargs, _popenargs = _cmdy_parse_args(
            self._name, args, kwargs
        )

        ready_args = (self._args or []) + _args
        ready_kwargs = self._kwargs.copy() if self._kwargs else {}
        ready_kwargs.update(_kwargs)
        ready_cfgargs = self._cfgargs.copy() if self._cfgargs else _Diot()
        ready_cfgargs.update(_cfgargs)
        ready_popenargs = self._popenargs.copy() if self._popenargs else _Diot()
        ready_popenargs.update(_popenargs)

        # update the executable
        exe = ready_cfgargs.pop('exe', None) or self._name

        will = _will()
        if will == 'bake':
            if args:
                raise CmdyBakingError('Must bake from keyword arguments.')
            return self.__class__(self._name, ready_args, ready_kwargs,
                                  ready_cfgargs, ready_popenargs)

        # Let CmdyHolding handle the result
        return CmdyHolding([exe] + ready_args, ready_kwargs,
                           ready_cfgargs, ready_popenargs, will)

    def bake(self):
        """Already done in __call__"""
        return self

    def __getattr__(self, name):
        self._args.append(name)
        return self

    b = bake

class CmdyHolding:
    """Command not running yet"""
    def __new__(cls, # pylint: disable=too-many-function-args
                args: list,
                kwargs: dict,
                cfgargs: _Diot,
                popenargs: _Diot,
                will: str = None):

        holding = super().__new__(cls)

        # Use the _onhold function, but fake an object
        if cls._onhold(_Diot(
                data=_Diot(hold=False),
                did='',
                will=will
        )):
            # __init__ automatically called
            return holding

        holding.__init__(args, kwargs, cfgargs, popenargs, will)
        result = holding.run()

        if not will:
            return result.wait()

        return result

    def __init__(self, args, kwargs, cfgargs, popenargs, will):
        # Attach the global EVENT here for later access

        # remember this for resetting
        self._reset_async = cfgargs['async']
        self.shell = cfgargs.shell
        self.encoding = cfgargs.encoding
        self.okcode = cfgargs.okcode
        self.timeout = cfgargs.timeout
        self.raise_ = cfgargs['raise']
        self.should_close_fds = _Diot()
        # Should I wait for the results, or just run asyncronouslly
        # This should be controlled by plugins
        # to communicate between each other
        # This only works in sync mode
        self.should_wait = False
        self.did = self.curr = ''
        self.will = will


        # pipes
        self.stdin = _subprocess.PIPE
        self.stdout = _subprocess.PIPE
        self.stderr = _subprocess.PIPE

        popenargs.shell = False

        self.popenargs = popenargs
        # data carried by actions (ie redirect, pipe, etc)
        self.data = _Diot({'async': cfgargs['async'], 'hold': False})
        self.cmd = _cmdy_compose_cmd(args, kwargs, shell=self.shell,
                                     prefix=cfgargs.prefix,
                                     sep=cfgargs.sep,
                                     dupkey=cfgargs.dupkey)

    def __repr__(self):
        return f"<CmdyHolding: {self.cmd}>"

    def reset(self):
        """Reset the holding object for reuse"""
        # pipes
        self.stdin = _subprocess.PIPE
        self.stdout = _subprocess.PIPE
        self.stderr = _subprocess.PIPE
        self.did = self.curr = self.will = ''

        self.should_close_fds = _Diot()
        self.data = _Diot({'async': self._reset_async, 'hold': False})
        return self

    @property
    def strcmd(self):
        """Get the stringified cmd"""
        return ' '.join(_quote(cmdpart) for cmdpart in self.cmd)

    def _run(self):
        try:
            return _subprocess.Popen(
                self.cmd,
                stdin=self.stdin,
                stdout=self.stdout,
                stderr=self.stderr,
                **self.popenargs
            )
        except FileNotFoundError as fnfe:
            raise CmdyExecNotFoundError(str(fnfe)) from None

    def _onhold(self, check_event=True):
        """Tell if I am on hold
        We should be on hold to run if:
        1. EVENT is set. This means that there are unconsumed pipes
        2. The world is on hold if `.h()` or `.hold()` is called earlier
        3. If a holding-left action will be taken
        4. If a holding-right action was taken

        Args:
            check_event (bool): Should we check if event is set as well?
                                We should ignore it if we are consuming a piping
        """
        return ((check_event and _CMDY_EVENT.is_set()) or
                self.data.hold or
                self.will in _CMDY_HOLDING_LEFT or
                self.did in _CMDY_HOLDING_RIGHT)

    def async_(self):
        """Put command in async mode"""
        if self.data['async']:
            raise CmdyActionError("Already in async mode.")

        self.data['async'] = True
        # update actions
        self.did, self.curr, self.will = self.curr, self.will, _will()

        if self._onhold():
            return self
        return self.run()

    a = async_

    def hold(self):
        """Put the command on hold"""
        # Whever hold is called
        self.data['hold'] = True
        self.did, self.curr, self.will = self.curr, self.will, _will()

        if self.data['async'] or len(self.data) > 2:
            raise CmdyActionError("Should be called in "
                                  "the first place: .h() or .hold()")
        return self

    h = hold

    def run(self, wait=None):
        """Run the command"""
        if wait is None:
            wait = self.should_wait
        if not self.data['async']:
            ret = CmdyResult(self._run(), self)
            if wait:
                return ret.wait()
            return ret
        return CmdyAsyncResult(self._run(), self)

class CmdyResult:

    """Sync version of result"""

    def __init__(self, proc, holding):
        self.proc = proc
        self.holding = holding
        self.did = self.curr = ''
        self.will = holding.will
        self._stdout = None
        self._stderr = None
        self.data = _Diot()
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
        return ' '.join(_quote(cmdpart) for cmdpart in self.cmd)

    def wait(self):
        """Wait until command is done
        """
        timeout = self.holding.timeout
        try:
            if timeout:
                self._rc = _curio.run(
                    _curio.timeout_after(timeout, self.proc.wait)
                )
            else:
                self._rc = _curio.run(self.proc.wait())
        except _curio.TaskTimeout:
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
        if self.holding.stdout != _subprocess.PIPE:
            # redirected, we are unable to fetch the stdout
            return None

        if self._stdout is not None:
            return self._stdout

        self._stdout = _CmdySyncStreamFromAsync(
            self.proc.stdout,
            encoding=self.holding.encoding
        ).dump()
        return self._stdout

    @property
    def stderr(self):
        """The stderr of the command"""
        if self.holding.stderr != _subprocess.PIPE:
            # redirected, we are unable to fetch the stdout
            return None

        if self._stderr is not None:
            return self._stderr
        self._stderr = _CmdySyncStreamFromAsync(
            self.proc.stderr,
            encoding=self.holding.encoding
        ).dump()
        return self._stderr

class CmdyAsyncResult(CmdyResult):
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
                    if _inspect.iscoroutine(coro):
                        await coro # pragma: no cover
        except AttributeError: # pragma: no cover
            pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        which = self.data.get('iter', {}).get('which', STDOUT)
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
                self._rc = await _curio.timeout_after(timeout, self.proc.wait)
            else:
                self._rc = await self.proc.wait()
        except _curio.TaskTimeout:
            raise CmdyTimeoutError("Timeout after "
                                   f"{self.holding.timeout} seconds.")
        else:
            if self._rc not in self.holding.okcode and self.holding.raise_:
                await _cmdy_raise_return_code_error(self)
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

def _cmdy_hook_class(cls):
    """Put hooks into the original class for extending"""
    # store the functions with the same name
    # that defined by different plugins
    # Note that current (most recently added) is not in the stack
    cls._plugin_stacks = {}

    def _original(self, fname):
        # callframe is oringally -1
        frame = self._plugin_callframe.setdefault(fname, -1)
        frame += 1
        self._plugin_callframe[fname] = frame
        return cls._plugin_stacks[fname][frame]
    cls._original = _original

    orig_init = cls.__init__
    def __init__(self, *args, **kwargs):
        self._plugin_callframe = {}
        orig_init(self, *args, **kwargs)

    cls.__init__ = __init__

    if cls is CmdyHolding:
        orig_reset = cls.reset
        def reset(self, *args, **kwargs):
            # clear the callframes as well
            self._plugin_callframe = {}
            orig_reset(self, *args, **kwargs)
            return self

        cls.reset = reset

    # this is not a decorator, we don't return cls

_cmdy_hook_class(CmdyHolding)
_cmdy_hook_class(CmdyResult)
# CmdyAsyncResult is a subclass of CmdyResult

def cmdy_plugin(cls):
    """A decorator to define a cmdy_plugin
    A cmdy_plugin should be a class and methods should be decorated by the hooks
    """
    orig_init = cls.__init__
    data = [val for val in cls.__dict__.values() if hasattr(val, 'enable')]

    def __init__(self):
        self.enabled = False
        self.enable()
        orig_init(self)

    def enable(self):
        for val in data:
            val.enable()
        self.enabled = True

    def disable(self):
        for val in data:
            val.disable()
        self.enabled = False

    cls.enable = enable
    cls.disable = disable
    cls.__init__ = __init__
    return cls

def _cmdy_plugin_funcname(func):
    funcname = func.__name__.rstrip('_')
    if funcname.startswith('__'):
        return funcname + '__'
    return funcname

def _cmdy_method_enable(cls, names, func):
    for name in names:
        # put original func into stack if any
        stack = cls._plugin_stacks.setdefault(name, [])
        orig_func = getattr(cls, name, None)

        if orig_func:
            stack.insert(0, orig_func)
        setattr(cls, name, func)

def _cmdy_method_disable(cls, names, func):
    for name in names:
        # remove the function from stack
        # and restore the latest defined one
        curr_func = getattr(cls, name)
        if curr_func is func:
            delattr(cls, name)

        if func in cls._plugin_stacks[name]:
            cls._plugin_stacks[name].remove(func)

        if not hasattr(cls, name) and cls._plugin_stacks[name]:
            setattr(cls, name, cls._plugin_stacks[name].pop(0))

def _cmdy_property_enable(cls, names, func):
    for name in names:
        stack = cls._plugin_stacks.setdefault(name, [])
        orig_prop = getattr(cls, name, None)
        if orig_prop:
            stack.insert(0, orig_prop)
        setattr(cls, name, property(func))

def _cmdy_property_disable(cls, names, func):
    for name in names:
        curr_prop = getattr(cls, name)
        if curr_prop.fget is func:
            delattr(cls, name)

        cls._plugin_stacks[name] = [prop for prop in cls._plugin_stacks[name]
                                    if prop.fget is not func]

        if not hasattr(cls, name) and cls._plugin_stacks[name]:
            setattr(cls, name, cls._plugin_stacks[name].pop(0))

def plugin_add_method(cls):
    """A decorator to add a method to a class"""
    def decorator(func):
        func.enable = lambda: _cmdy_method_enable(
            cls, [_cmdy_plugin_funcname(func)], func
        )
        func.disable = lambda: _cmdy_method_disable(
            cls, [_cmdy_plugin_funcname(func)], func
        )
        return func
    return decorator

def plugin_add_property(cls):
    """A decorator to add a property to a class"""
    def decorator(func):
        func.enable = lambda: _cmdy_property_enable(
            cls, [_cmdy_plugin_funcname(func)], func
        )
        func.disable = lambda: _cmdy_property_disable(
            cls, [_cmdy_plugin_funcname(func)], func
        )
        return func
    return decorator

def _plugin_then(cls, func, aliases=None, *,
                 final: bool = False, hold_right: bool = False):
    aliases = aliases or []
    if not isinstance(aliases, list):
        aliases = [alias.strip() for alias in aliases.split(',')]
    aliases.insert(0, _cmdy_plugin_funcname(func))

    finals = _CMDY_HOLDING_FINALS if cls is CmdyHolding else _CMDY_RESULT_FINALS
    if final:
        finals.extend(aliases)

    @_wraps(func)
    def wrapper(self, *args, **kwargs):
        # Update actions
        self.did, self.curr, self.will = self.curr, self.will, _will()

        if self.curr in finals and self.will in _CMDY_HOLDING_LEFT:
            raise CmdyActionError("Action taken after a final action.")
        # Initialize data
        # Make it True to tell future actions that I have been called
        # Just in case some plugins forget to do this
        self.data.setdefault(_cmdy_plugin_funcname(func), {})
        return func(self, *args, **kwargs)

    wrapper.enable = lambda: _cmdy_method_enable(cls, aliases, wrapper)
    wrapper.disable = lambda: _cmdy_method_disable(cls, aliases, wrapper)

    if cls is CmdyHolding:
        _CMDY_HOLDING_LEFT.extend(aliases)
        if hold_right:
            _CMDY_HOLDING_RIGHT.extend(aliases)
    return wrapper

def plugin_hold_then(alias_or_func=None,
                     *, final: bool = False,
                     hold_right: bool = True):
    """What to do if a command is holding

    Args:
        alias_or_func (str|list|Callable): Direct decorator or with kwargs
        final (bool): If this is a final action
        hold_right (bool): Tell previous actions that I should be on hold.
                           But make sure running will be taken good care of.
    """
    aliases = None if callable(alias_or_func) else alias_or_func
    func = alias_or_func if callable(alias_or_func) else None

    if func:
        return _plugin_then(CmdyHolding, func, aliases,
                            final=final, hold_right=hold_right)

    return lambda func: _plugin_then(CmdyHolding, func, aliases,
                                     final=final, hold_right=hold_right)

def plugin_run_then(alias_or_func=None, *, final: bool = False):
    """What to do when a command is running"""
    aliases = None if callable(alias_or_func) else alias_or_func
    func = alias_or_func if callable(alias_or_func) else None

    if func:
        return _plugin_then(CmdyResult, func, aliases, final=final)

    return lambda func: _plugin_then(CmdyResult, func, aliases, final=final)

def plugin_run_then_async(alias_or_func):
    """What to do when a command is running asyncronously"""
    aliases = None if callable(alias_or_func) else alias_or_func
    func = alias_or_func if callable(alias_or_func) else None

    if func:
        return _plugin_then(CmdyAsyncResult, func, aliases)

    return lambda func: _plugin_then(CmdyAsyncResult, func, aliases)

# pylint: disable=access-member-before-definition
# pylint: disable=attribute-defined-outside-init

@cmdy_plugin
class CmdyPluginRedirect:
    """Plugin: redirect
    Redirect the in/out to somewhere else"""
    def _redirect(self: CmdyHolding, which: list, append: bool,
                  file) -> bool:
        # add file-like type suport for file
        if not self.data.get('redirect'):
            raise CmdyActionError('Cannot redirect a non-redirecting command. '
                                  'Did you forget to call '
                                  '.r(), .redir() or .redirect()?')
        curr_pipe = which.pop(0)
        self.data.redirect.which = which

        if curr_pipe == STDIN:
            if isinstance(file, CmdyResult):
                self.stdin = file.proc.stdout
                self.should_close_fds.stdin = None
            elif hasattr(file, 'read'):
                self.stdin = file
                self.should_close_fds.stdin = None
            else:
                self.stdin = open(file, 'r', encoding=self.encoding)
                self.should_close_fds.stdin = self.stdin

        elif curr_pipe == STDOUT:
            if file == STDERR:
                raise CmdyActionError("Cannot redirect STDOUT to STDERR.")
            if hasattr(file, 'read'):
                self.stdout = file
                self.should_close_fds.stdout = None
            else:
                self.stdout = open(file, 'a' if append else 'w',
                                   encoding=self.encoding)
                self.should_close_fds.stdout = self.stdout
        elif curr_pipe == STDERR:
            if file == STDOUT:
                self.stderr = STDOUT
                self.should_close_fds.stderr = None
            elif hasattr(file, 'read'):
                self.stderr = file
                self.should_close_fds.stderr = None
            else:
                self.stderr = open(file, 'a' if append else 'w',
                                   encoding=self.encoding)
                self.should_close_fds.stderr = self.stderr
        else:
            raise CmdyActionError("Don't know what to redirect. "
                                  "Expecting STDIN, STDOUT or STDERR")

        # Since we are holding right, set did to ''
        # to let the right action run
        self.did = ''
        if not which and not self._onhold():
            #self.data.redirect = {}
            return self.run()

        return self


    @plugin_add_method(CmdyHolding)
    def __gt__(self, file):
        which = self.data.get('redirect', {}).get('which', [STDOUT])
        return CmdyPluginRedirect._redirect(self, list(which), False, file)

    @plugin_add_method(CmdyHolding)
    def __lt__(self, file):
        which = self.data.get('redirect', {}).get('which', [STDOUT])
        return CmdyPluginRedirect._redirect(self, list(which), False, file)

    @plugin_add_method(CmdyHolding)
    def __xor__(self, file):
        """Priority issue with gt (>)
        We need brackets to ensure the order:
        `(cmdy.ls().r(REDIR_RSPT) > outfile) > errfile`
        To avoid this, use xor (^) instead
        """
        which = self.data.get('redirect', {}).get('which', [STDOUT])
        if which[0] == STDIN:
            return self.__lt__(file)
        return self.__gt__(file)

    @plugin_add_method(CmdyHolding)
    def __rshift__(self, file):
        which = self.data.get('redirect', {}).get('which', [STDOUT])
        return CmdyPluginRedirect._redirect(self, list(which), True, file)

    @plugin_hold_then('r,redir', hold_right=True)
    def redirect(self, *which):
        """Redirect the input/output"""

        # We should wait for the command to finish, so that we
        # don't leave it piping in background
        # To do so, use it in async mode
        self.should_wait = True

        which = which or [STDOUT]

        # since this is final, so
        # cmdy.ls().r().r() will never happen
        if self.data.redirect: # pragma: no cover
            raise CmdyActionError('Unconsumed redirect action.')

        # initialize data
        self.data.redirect.which = list(which)

        return self

@cmdy_plugin
class CmdyPluginFg:
    """Plugin: fg
    Running command in foreground
    Using sys.stdout and sys.stderr"""
    async def _feed(self: CmdyResult,
                    poll_interval: float = 0.1):
        """Try to feed stdout/stderr to sys.stdout/sys.stderr"""

        async def _feed_one(instream, outstream):
            try:
                out = await _curio.timeout_after(poll_interval,
                                                 instream.__anext__)
            except _curio.TaskTimeout:
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
                out_live = await _feed_one(self.proc.stdout, _sys.stdout)
            if err_live:
                err_live = await _feed_one(self.proc.stderr, _sys.stderr)

        if isinstance(self, CmdyAsyncResult):
            await self.wait()

    @plugin_hold_then('fg', final=True, hold_right=False)
    def foreground(self, stdin: bool = False,
                   poll_interval: bool = .1
                   ): #-> Union[CmdyHolding, CmdyResult]
        """Running command in foreground
        Using sys.stdout and sys.stderr"""
        self.data.foreground.stdin = stdin
        self.data.foreground.poll_interval = poll_interval

        if not self._onhold():
            return self.run()
        return self

    @plugin_add_method(CmdyHolding)
    def run(self, wait=None):
        """Run the command and bump stdout/stderr to sys'"""
        orig_run = self._original('run')

        if not self.data.get('foreground'):
            return orig_run(self, wait)

        if ((self.data.foreground.stdin and self.stdin != _subprocess.PIPE) or
                self.stdout != _subprocess.PIPE or
                self.stderr != _subprocess.PIPE):
            _warnings.warn("Previous redirected pipe will be ignored.")

        # fileinput.input is good to use here
        # as it has fileno()
        self.stdin = (_fileinput.input() if self.data.foreground.stdin
                      else self.stdin)
        self.stdout = _subprocess.PIPE
        self.stderr = _subprocess.PIPE

        ret = orig_run(self, False)

        _curio.run(CmdyPluginFg._feed(ret, self.data.foreground.poll_interval))
        # we can't in self.wait() in _curio.run, because there is
        # already a _curio kernel running inside CmdyResult.wait()
        return ret if isinstance(ret, CmdyAsyncResult) else ret.wait()

@cmdy_plugin
class CmdyPluginPipe:
    """Plugin: pipe
    Allow piping from one command to another
    `cmdy.ls().pipe() | cmdy.cat()`
    """
    @plugin_add_property(CmdyResult)
    def piped_cmds(self):
        """Get cmds that along the piping path

        Example:
            ```python
            c = cmdy.echo(123).p() | cmdy.cat()
            c.piped_cmds == ['echo 123', 'cat']
            ```
        """
        piped_from = self.holding.data.get('pipe', {}).get('from')
        if piped_from:
            return piped_from.piped_cmds + [self.cmd]
        return [self.cmd]

    @plugin_add_property(CmdyResult)
    def piped_strcmds(self):
        """Get cmds that along the piping path

        Example:
            ```python
            c = cmdy.echo(123).p() | cmdy.cat()
            c.piped_cmds == ['echo 123', 'cat']
            ```
        """
        piped_from = self.holding.data.get('pipe', {}).get('from')
        if piped_from:
            return piped_from.piped_strcmds + [self.strcmd]
        return [self.strcmd]

    @plugin_add_property(CmdyHolding)
    def piped_cmds_(self):
        """Get cmds that along the piping path

        Example:
            ```python
            c = cmdy.echo(123).p() | cmdy.cat()
            c.piped_cmds == ['echo 123', 'cat']
            ```
        """
        piped_from = self.data.get('pipe', {}).get('from')
        if piped_from:
            return piped_from.piped_cmds + [self.cmd]
        return [self.cmd]

    @plugin_add_property(CmdyHolding)
    def piped_strcmds_(self):
        """Get cmds that along the piping path

        Example:
            ```python
            c = cmdy.echo(123).p() | cmdy.cat()
            c.piped_cmds == ['echo 123', 'cat']
            ```
        """
        piped_from = self.data.get('pipe', {}).get('from')
        if piped_from:
            return piped_from.piped_strcmds + [self.strcmd]
        return [self.strcmd]

    @plugin_add_method(CmdyHolding)
    def __or__(self, other: CmdyHolding):

        if not self.data.get('pipe'):
            raise CmdyActionError('Piping options have been consumed or trying '
                                  'to pipe from non-piping command')

        assert isinstance(other, CmdyHolding), ("Can only pipe to "
                                                "a CmdyHolding object.")

        other_pipe_data = other.data.setdefault('pipe', {})
        other_pipe_data['from'] = self

        # We shall not check the event, because the purpose here
        # is to clear the EVENT
        # But we need to check if other is also a piping command
        # which will be set if .pipe() is called
        if (not other._onhold(check_event=False) and
                not other.data.get('pipe', {}).get('which')):
            _CMDY_EVENT.clear()
            return other.run()

        return other

    @plugin_hold_then('p')
    def pipe(self, which=None):
        """Allow command piping"""
        if self.data.get('pipe'):
            raise CmdyActionError("Unconsumed piping action.")

        # initialize data
        which = which or STDOUT
        self.data.pipe.which = which

        if ((which == STDOUT and self.stdout != _subprocess.PIPE) or
                (which == STDERR and self.stderr != _subprocess.PIPE)):

            raise CmdyActionError("Cannot pipe from a redirected PIPE.")
        _CMDY_EVENT.set()
        return self

    @plugin_add_method(CmdyHolding)
    def run(self, wait=None):
        """From from prior piped command"""
        orig_run = self._original('run')

        if not self.data.get('pipe', {}).get('from'):
            return orig_run(self, wait)

        prior = self.data.pipe['from']
        prior_result = prior.run()

        self.stdin = (prior_result.proc.stdout
                      if prior.data.pipe.which == STDOUT
                      else prior_result.proc.stderr)

        return orig_run(self, wait)

@cmdy_plugin
class CmdyPluginIter:
    """Plugin: iter
    Iterator over results
    """
    @plugin_add_method(CmdyResult)
    def __iter__(self):
        return self

    @plugin_add_property(CmdyResult)
    def stdout(self):
        """Get the iterable of stdout"""

        if self.holding.stdout != _subprocess.PIPE:
            # redirected, we are unable to fetch the stdout
            return None

        if self._stdout is not None:
            return self._stdout

        orig_stdout = self._original('stdout')

        if not self.data.get('iter'):
            return orig_stdout.fget(self)

        which = self.data.iter.get('which', STDOUT)
        self._stdout = _CmdySyncStreamFromAsync(self.proc.stdout,
                                                self.holding.encoding)
        if which != STDOUT:
            self._stdout = self._stdout.dump()
        return self._stdout

    @plugin_add_property(CmdyResult)
    def stderr(self):
        """Get the iterable of stderr"""

        if self.holding.stderr != _subprocess.PIPE:
            # redirected, we are unable to fetch the stdout
            return None

        if self._stderr is not None:
            return self._stderr

        orig_stderr = self._original('stderr')

        if not self.data.get('iter'):
            return orig_stderr.fget(self)

        which = self.data.iter.get('which', STDOUT)
        self._stderr = _CmdySyncStreamFromAsync(self.proc.stderr,
                                                self.holding.encoding)
        if which != STDERR:
            self._stderr = self._stderr.dump()
        return self._stderr

    @plugin_add_method(CmdyResult)
    def __next__(self):
        return self.next()

    @plugin_add_method(CmdyResult)
    def next(self, timeout=None):
        """Get next row, with a timeout limit
        If nothing produced after the timeout, returns an empty string
        """
        which = self.data.get('iter', {}).get('which', STDOUT)
        try:
            if which == STDOUT:
                if not isinstance(self.stdout, _CmdySyncStreamFromAsync):
                    raise TypeError('CmdyResult object is not iterable '
                                    'synchronously')
                return self.stdout.next(timeout)

            if not isinstance(self.stderr, _CmdySyncStreamFromAsync):
                raise TypeError('CmdyResult object is not iterable '
                                'synchronously')
            return self.stderr.next(timeout)
        except StopIteration:
            # self.data.iter = {}
            self.wait()
            raise

    @plugin_run_then('it')
    def iter(self, which=None): # pylint: disable=redefined-builtin
        """Iterator over STDOUT or STDERR of a CmdyResult object"""

        which = which or STDOUT
        self.data.iter.which = which

        if (
                (which == STDOUT and
                 self.holding.stdout != _subprocess.PIPE) or
                (which == STDERR and
                 self.holding.stderr != _subprocess.PIPE)
        ):
            raise CmdyActionError("Cannot iterate from a redirected PIPE.")

        return self

    @plugin_hold_then('it', final=True, hold_right=False)
    def iter_(self, which=None):
        """Put holding on running and iterator over STDOUT or STDERR"""
        self.should_wait = False

        if self._onhold():
            return self
        return self.run().iter(which)

@cmdy_plugin
class CmdyPluginValue:
    """Plugins: Value casting
    This is blocking in sync mode
    """
    @plugin_run_then
    def str(self, which=None): # pylint: disable=redefined-builtin
        """Fetch the results as a string"""
        which = which or STDOUT
        if (
                (which == STDOUT and
                 self.holding.stdout != _subprocess.PIPE) or
                (which == STDERR and
                 self.holding.stderr != _subprocess.PIPE)
        ):
            raise CmdyActionError("Cannot fetch results from "
                                  "a redirected PIPE.")

        if which not in (STDOUT, STDERR):
            raise CmdyActionError("Expecting STDOUT or STDERR for which.")

        # cached results
        if which == STDOUT and getattr(self, '_stdout_str', None) is not None:
            return self._stdout_str
        if which == STDERR and getattr(self, '_stderr_str', None) is not None:
            return self._stderr_str

        self.wait()
        out = self.stdout if which == STDOUT else self.stderr
        if isinstance(out, (str, bytes)):
            setattr(self,
                    '_stdout_str' if which == STDOUT else '_stderr_str',
                    out)
            return out

        ret = ''.join(out) if self.holding.encoding else b''.join(out)
        setattr(self, '_stdout_str' if which == STDOUT else '_stderr_str', ret)
        return ret

    @plugin_run_then
    async def astr(self, which=None):
        """Async version of str"""

        which = which or STDOUT
        if (
                (which == STDOUT and
                 self.holding.stdout != _subprocess.PIPE) or
                (which == STDERR and
                 self.holding.stderr != _subprocess.PIPE)
        ):
            raise CmdyActionError("Cannot fetch results from "
                                  "a redirected PIPE.")

        if which not in (STDOUT, STDERR):
            raise CmdyActionError("Expecting STDOUT or STDERR for which.")

        # cached results
        if which == STDOUT and getattr(self, '_stdout_str', None) is not None:
            return self._stdout_str
        if which == STDERR and getattr(self, '_stderr_str', None) is not None:
            return self._stderr_str

        await self.wait()
        ret = ((await self.stdout.read()) if which == STDOUT
               else (await self.stderr.read()))

        if self.holding.encoding:
            value = ret.decode(self.holding.encoding)
            setattr(self, '_stdout_str' if which == STDOUT else '_stderr_str',
                    value)
            return value

        setattr(self, '_stdout_str' if which == STDOUT else '_stderr_str', ret)
        return ret

    @plugin_add_method(CmdyResult)
    def __contains__(self, item):
        return item in self.str()

    @plugin_add_method(CmdyResult)
    def __eq__(self, other):
        return self.str() == other

    @plugin_add_method(CmdyResult)
    def __ne__(self, other):
        return not self.__eq__(other)

    @plugin_add_method(CmdyResult)
    def __str__(self):
        return self.str()

    @plugin_add_method(CmdyResult)
    def __getattr__(self, name):
        if name in dir('') and not name.startswith('__'):
            return getattr(self.str(), name)
        return self.__getattribute__(name)

    @plugin_run_then
    def int(self, which=None): # pylint: disable=redefined-builtin
        """Cast value to int"""
        return int(self.str(which))

    @plugin_run_then
    async def aint(self, which=None):
        """Async version of int"""
        return int(await self.astr(which))

    @plugin_run_then
    def float(self, which=None): # pylint: disable=redefined-builtin
        """Cast value to float"""
        return float(self.str(which))

    @plugin_run_then
    async def afloat(self, which=None):
        """Async version of float"""
        return float(await self.astr(which))

# One can disable builtin plugins
CMDY_PLUGIN_FG = CmdyPluginFg()
CMDY_PLUGIN_ITER = CmdyPluginIter()
CMDY_PLUGIN_REDIRECT = CmdyPluginRedirect()
CMDY_PLUGIN_PIPE = CmdyPluginPipe()
CMDY_PLUGIN_VALUE = CmdyPluginValue()

@_modkit.delegate
def _modkit_delegate(name):
    return Cmdy(name)

@_modkit.call
def _modkit_call(module, assigned_to, **kwargs):
    # Module is deeply copied
    # But we need to reference all Exceptions
    # So that we can do:
    # ```python
    # from cmdy import CmdyExecNotFoundError
    # sh = cmdy()
    # sh.nonexisting()
    # # raises CmdyExecNotFoundError
    # # instead of sh.CmdyExecNotFoundError
    newmod = module.__bake__(assigned_to)
    newmod.CmdyBakingError = module.CmdyBakingError
    newmod.CmdyActionError = module.CmdyActionError
    newmod.CmdyTimeoutError = module.CmdyActionError
    newmod.CmdyExecNotFoundError = module.CmdyExecNotFoundError
    newmod.CmdyReturnCodeError = module.CmdyReturnCodeError

    newmod._CMDY_BAKED_ARGS.update(module._CMDY_BAKED_ARGS)
    newmod._CMDY_BAKED_ARGS.update(kwargs)
    return newmod

# not banning anything with modkit
# but conventionally names start with _ should not be exported
