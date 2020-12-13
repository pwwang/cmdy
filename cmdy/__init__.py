"""A handy package to run command from python"""
# We have to inevitably put stuff in the main module for
# module baking purposes
#
# pylint: disable=too-many-lines
#
# ----------------------------------------------------------
# Naming rules to save the names for the uses of
# >>> from cmdy import ...
#
# 1. Anything that is imported will be prefixed with '_'
# 2. Any constants to be exported will be prefixed with 'CMDY_'
# 3. Any functions to be exported will be prefixed with 'cmdy_'
# 4. 3 also includes plugin hooks
# ----------------------------------------------------------
#
import sys as _sys
import fileinput as _fileinput

from threading import Event as _Event
from shlex import quote as _quote
import warnings as _warnings
import inspect as _inspect
from diot import Diot as _Diot
from simpleconf import Config as _Config
import curio as _curio
from curio import subprocess as _subprocess
from varname import will as _will, varname as _varname
from modkit import install as _install, bake as _bake
from .cmdy_util import (STDIN, STDOUT, STDERR, DEVNULL,
                        CmdyActionError, CmdyTimeoutError,
                        CmdyExecNotFoundError, CmdyReturnCodeError,
                        _cmdy_raise_return_code_error,
                        _cmdy_compose_cmd, _cmdy_parse_args,
                        _cmdy_compose_arg_segment,
                        _cmdy_parse_single_kwarg,
                        _cmdy_property_or_method,
                        _CmdySyncStreamFromAsync)
from .cmdy_plugin import _cmdy_hook_class, _CmdyPluginProxy

__version__ = "0.4.3"

# pylint: disable=invalid-overridden-method

# We cannot define the variables that need to be baked
# in submodules, because we don't want to deepcopy the
# whole module.
_CMDY_DEFAULT_CONFIG = _Diot({
    'async': False,
    'deform': lambda name: name.replace('_', '-'),
    'dupkey': False,
    'exe': None,
    'encoding': 'utf-8',
    'okcode': [0],
    'prefix': 'auto',
    'raise': True,
    'sep': ' ',
    'shell': False,
    'sub': False,
    'timeout': 0
})

CMDY_CONFIG = _Config()
CMDY_CONFIG._load(
    dict(default=_CMDY_DEFAULT_CONFIG),
    '~/.cmdy.toml',
    './.cmdy.toml',
    'CMDY.osenv'
)

_CMDY_BAKED_ARGS = _Diot()
_CMDY_EVENT = _Event()

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
        # cmdy.ls(l=True)
        self._kwargs: list = kwargs or {}
        # cmdy.ls(cmdy_prefix="-", l=...)
        self._cfgargs: _Diot = cfgargs
        # cmdy.ls(cmdy_stdin="/dev/stdin")
        self._popenargs: _Diot = popenargs

    def __call__(self, *args, **kwargs):
        _args, _kwargs, _cfgargs, _popenargs = _cmdy_parse_args(
            self._name, args, kwargs, CMDY_CONFIG, _CMDY_BAKED_ARGS
        )
        ready_args = (self._args or []) + _args
        ready_kwargs = self._kwargs.copy() if self._kwargs else {}
        ready_kwargs.update(_kwargs)
        ready_cfgargs = CMDY_CONFIG.copy()
        ready_cfgargs.update(self._cfgargs or {})
        ready_cfgargs.update(_cfgargs)
        ready_popenargs = self._popenargs.copy() if self._popenargs else _Diot()
        ready_popenargs.update(_popenargs)

        # clear direct subcommand for reuse
        self._args = []

        if ready_cfgargs.pop('sub', False):
            return CmdyHoldingWithSub(
                self._name, ready_args, ready_kwargs,
                ready_cfgargs, ready_popenargs
            )

        # update the executable
        exe = ready_cfgargs.pop('exe', None) or self._name

        # Let CmdyHolding handle the result
        return CmdyHolding([str(exe)] + ready_args, ready_kwargs,
                           ready_cfgargs, ready_popenargs,
                           _will(raise_exc=False))

    def _bake(self, **kwargs):
        """Bake a command"""
        if _will(raise_exc=False):
            raise CmdyActionError("Baking Cmdy object is supposed to "
                                  "be reused.")

        pure_cmd_kwargs, global_config, popen_config = (
            _cmdy_parse_single_kwarg(kwargs, True,
                                     self._cfgargs or CMDY_CONFIG)
        )

        kwargs = self._kwargs.copy() if self._kwargs else {}
        kwargs.update(pure_cmd_kwargs)

        config = self._cfgargs.copy() if self._cfgargs else _Diot()
        config.update(global_config)

        pconfig = self._popenargs.copy() if self._popenargs else _Diot()
        pconfig.update(popen_config)

        return self.__class__(self._name, self._args,
                              kwargs, config, pconfig)


    def __getattr__(self, name):
        """Direct subcommand"""
        if name in ('b', 'bake'):
            return self._bake
        # when calling getattr(cmdy, '__wrapped__'), should return False
        if name[:2] == name[-2:] and len(name) > 4:
            raise AttributeError

        self._args.append(name)
        return self

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
        self.cmd = _cmdy_compose_cmd(args, kwargs,
                                     cfgargs, shell=self.shell)

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

    @property
    @_cmdy_property_or_method
    def async_(self):
        """Put command in async mode"""
        if self.data['async']:
            raise CmdyActionError("Already in async mode.")

        self.data['async'] = True
        # update actions
        self.did, self.curr, self.will = (
            self.curr, self.will, _will(2, raise_exc=False)
        )
        if self._onhold():
            return self
        return self.run()

    a = async_

    @property
    @_cmdy_property_or_method
    def hold(self):
        """Put the command on hold"""
        # Whever hold is called
        self.data['hold'] = True
        self.did, self.curr, self.will = (
            self.curr, self.will, _will(2, raise_exc=False)
        )

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

class CmdyHoldingWithSub:
    """A command with subcommands"""
    def __init__(self, name, args, kwargs, cfgargs, popenargs):
        self._name = name
        self._args = args
        self._kwargs = kwargs
        self._cfgargs = cfgargs
        self._popenargs = popenargs

    def __getattr__(self, name):
        args = _cmdy_compose_arg_segment(self._kwargs, self._cfgargs)
        return Cmdy(self._name,
                    self._args + args + [name],
                    {},
                    self._cfgargs,
                    self._popenargs)

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
            self.proc.kill()
            raise CmdyTimeoutError("Timeout after "
                                   f"{self.holding.timeout} seconds.") from None
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

_cmdy_hook_class(CmdyHolding)
_cmdy_hook_class(CmdyResult)
# CmdyAsyncResult is a subclass of CmdyResult
_CMDY_PLUGIN_PROXY = _CmdyPluginProxy(CmdyHolding,
                                      CmdyResult,
                                      CmdyAsyncResult,
                                      _CMDY_HOLDING_LEFT,
                                      _CMDY_HOLDING_RIGHT,
                                      _CMDY_HOLDING_FINALS,
                                      _CMDY_RESULT_FINALS)
# Expose hooks
# pylint: disable=invalid-name
cmdy_plugin = _CMDY_PLUGIN_PROXY.hook_plugin()
cmdy_plugin_add_method = _CMDY_PLUGIN_PROXY.hook_add_method()
cmdy_plugin_add_property = _CMDY_PLUGIN_PROXY.hook_add_property()
cmdy_plugin_hold_then = _CMDY_PLUGIN_PROXY.hook_hold_then()
cmdy_plugin_run_then = _CMDY_PLUGIN_PROXY.hook_run_then()
cmdy_plugin_async_run_then = _CMDY_PLUGIN_PROXY.hook_async_run_then()
# pylint: enable=invalid-name

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

    @cmdy_plugin_add_method(CmdyHolding)
    def __gt__(self, file):
        which = self.data.get('redirect', {}).get('which', [STDOUT])
        return CmdyPluginRedirect._redirect(self, list(which), False, file)

    @cmdy_plugin_add_method(CmdyHolding)
    def __lt__(self, file):
        which = self.data.get('redirect', {}).get('which', [STDOUT])
        return CmdyPluginRedirect._redirect(self, list(which), False, file)

    @cmdy_plugin_add_method(CmdyHolding)
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

    @cmdy_plugin_add_method(CmdyHolding)
    def __rshift__(self, file):
        which = self.data.get('redirect', {}).get('which', [STDOUT])
        return CmdyPluginRedirect._redirect(self, list(which), True, file)

    @cmdy_plugin_hold_then('r,redir', hold_right=True)
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
                    poll_interval: float):
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

    async def _timeout_wrapper(self: CmdyResult,
                               poll_interval: float):
        if self.holding.timeout:
            try:
                await _curio.timeout_after(
                    self.holding.timeout,
                    CmdyPluginFg._feed,
                    self,
                    poll_interval
                )
            except _curio.TaskTimeout:
                raise CmdyTimeoutError(
                    f"Timeout after {self.holding.timeout} seconds."
                ) from None
        else:
            await CmdyPluginFg._feed(self, poll_interval)

    @cmdy_plugin_hold_then('fg', final=True, hold_right=False)
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

    @cmdy_plugin_add_method(CmdyHolding)
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

        # we should handle timeout here, since we are not waiting
        _curio.run(CmdyPluginFg._timeout_wrapper(
            ret, self.data.foreground.poll_interval
        ))
        # we can't in self.wait() in _curio.run, because there is
        # already a _curio kernel running inside CmdyResult.wait()
        return ret if isinstance(ret, CmdyAsyncResult) else ret.wait()

@cmdy_plugin
class CmdyPluginPipe:
    """Plugin: pipe
    Allow piping from one command to another
    `cmdy.ls().pipe() | cmdy.cat()`
    """
    @cmdy_plugin_add_property(CmdyResult)
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

    @cmdy_plugin_add_property(CmdyResult)
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

    @cmdy_plugin_add_property(CmdyHolding)
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

    @cmdy_plugin_add_property(CmdyHolding)
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

    @cmdy_plugin_add_method(CmdyHolding)
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

    @cmdy_plugin_hold_then('p')
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

    @cmdy_plugin_add_method(CmdyHolding)
    def run(self, wait=None):
        """From from prior piped command"""
        orig_run = self._original('run')

        if not self.data.get('pipe', {}).get('from'):
            return orig_run(self, wait)

        prior = self.data.pipe['from']
        prior_result = prior.run(False)
        self.data.pipe['from'] = prior

        self.stdin = (prior_result.proc.stdout
                      if prior.data.pipe.which == STDOUT
                      else prior_result.proc.stderr)

        ret = orig_run(self, wait)
        prior_result.wait()
        return ret


@cmdy_plugin
class CmdyPluginIter:
    """Plugin: iter
    Iterator over results
    """
    @cmdy_plugin_add_method(CmdyResult)
    def __iter__(self):
        return self

    @cmdy_plugin_add_property(CmdyResult)
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

    @cmdy_plugin_add_property(CmdyResult)
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

    @cmdy_plugin_add_method(CmdyResult)
    def __next__(self):
        return self.next() # pylint: disable=not-callable

    @cmdy_plugin_add_method(CmdyResult)
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

    @cmdy_plugin_run_then('it')
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

    @cmdy_plugin_hold_then('it', final=True, hold_right=False)
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
    @cmdy_plugin_run_then
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

    @cmdy_plugin_run_then
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

    @cmdy_plugin_add_method(CmdyResult)
    def __contains__(self, item):
        return item in self.str()

    @cmdy_plugin_add_method(CmdyResult)
    def __eq__(self, other):
        return self.str() == other

    @cmdy_plugin_add_method(CmdyResult)
    def __ne__(self, other):
        return not self.__eq__(other)

    @cmdy_plugin_add_method(CmdyResult)
    def __str__(self):
        return self.str()

    @cmdy_plugin_add_method(CmdyResult)
    def __getattr__(self, name):
        if name in dir('') and not name.startswith('__'):
            return getattr(self.str(), name)
        return self.__getattribute__(name)

    @cmdy_plugin_run_then
    def int(self, which=None): # pylint: disable=redefined-builtin
        """Cast value to int"""
        return int(self.str(which))

    @cmdy_plugin_run_then
    async def aint(self, which=None):
        """Async version of int"""
        return int(await self.astr(which))

    @cmdy_plugin_run_then
    def float(self, which=None): # pylint: disable=redefined-builtin
        """Cast value to float"""
        return float(self.str(which))

    @cmdy_plugin_run_then
    async def afloat(self, which=None):
        """Async version of float"""
        return float(await self.astr(which))

# One can disable builtin plugins
CMDY_PLUGIN_FG = CmdyPluginFg()
CMDY_PLUGIN_ITER = CmdyPluginIter()
CMDY_PLUGIN_REDIRECT = CmdyPluginRedirect()
CMDY_PLUGIN_PIPE = CmdyPluginPipe()
CMDY_PLUGIN_VALUE = CmdyPluginValue()

def __getattr__(name):
    return Cmdy(name)

def __call__(**kwargs):
    new_name = _varname(2)
    new_mod = _bake(new_name)

    new_mod._CMDY_BAKED_ARGS.update(kwargs)
    return new_mod

_install()
