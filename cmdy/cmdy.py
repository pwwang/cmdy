from shlex import quote
from typing import TYPE_CHECKING

from curio import subprocess
from diot import Diot
from varname import will

from .cmdy_defaults import get_config
from .cmdy_exceptions import CmdyExecNotFoundError, CmdyActionError
from .cmdy_utils import (
    parse_args,
    compose_arg_segment,
    compose_cmd,
    property_or_method,
    parse_single_kwarg,
)

if TYPE_CHECKING:
    from .cmdy_bakeable import Bakeable


class Cmdy:
    def __init__(self, name: str, bakeable: "Bakeable", args: Diot = None):
        self._name = name
        self._bakeable = bakeable
        self._args = args or Diot()
        self._args.setdefault("args", [])
        self._args.setdefault("kwargs", {})
        self._args.setdefault("config", {})
        self._args.setdefault("popen", {})

    def __repr__(self) -> str:
        return f"<Cmdy: {self._name} {self._args.args} @ {hex(id(self))}>"

    def __call__(self, *args, **kwargs):
        config = get_config()
        args = parse_args(
            self._name, args, kwargs, config, self._bakeable._baking_args
        )
        ready_args = self._args.args.copy() + args.args
        ready_kwargs = self._args.kwargs.copy()
        ready_kwargs.update(args.kwargs)
        ready_config = config.copy()
        ready_config.update(self._args.config)
        ready_config.update(args.config)
        ready_popen = self._args.popen.copy()
        ready_popen.update(args.popen)

        # clear direct subcommand for reuse
        self._args.args = []

        if ready_config.pop("sub", False):
            return CmdyHoldingWithSub(
                self._name,
                Diot(
                    args=ready_args,
                    kwargs=ready_kwargs,
                    config=ready_config,
                    popen=ready_popen,
                ),
                self._bakeable,
            )

        # update the executable
        exe = ready_config.pop("exe", None) or self._name
        # next attribute
        next_attr = will(raise_exc=False)

        # Let CmdyHolding handle the result
        return self._bakeable.CmdyHolding(
            Diot(
                args=[str(exe)] + ready_args,
                kwargs=ready_kwargs,
                config=ready_config,
                popen=ready_popen,
            ),
            self._bakeable,
            next_attr,
        )

    def _(self, **kwargs):
        """Bake a command"""
        if will(raise_exc=False):
            raise CmdyActionError(
                "Baking Cmdy object is supposed to be reused."
            )

        pure_cmd_kwargs, global_config, popen_config = parse_single_kwarg(
            kwargs, True, self._args.config or get_config()
        )

        kwargs = self._args.kwargs.copy() if self._args.kwargs else {}
        kwargs.update(pure_cmd_kwargs)

        config = self._args.config.copy() if self._args.config else Diot()
        config.update(global_config)

        pconfig = self._args.popen.copy() if self._args.popen else Diot()
        pconfig.update(popen_config)

        return self.__class__(
            self._name,
            self._bakeable,
            Diot(
                args=self._args.args,
                kwargs=kwargs,
                config=config,
                popen=pconfig,
            ),
        )

    def __getattr__(self, name):
        """Direct subcommand"""
        # when calling getattr(cmdy, '__wrapped__'), should return False
        if name[:2] == "__":  # pragma: no cover
            raise AttributeError

        self._args.args.append(name)
        return self


class CmdyHoldingWithSub:
    """A command with subcommands"""

    def __init__(self, name, args, bakeable):
        self._name = name
        self._args = args
        self._bakeable = bakeable

    def __getattr__(self, name):
        args = compose_arg_segment(self._args.kwargs, self._args.config)
        return Cmdy(
            self._name,
            self._bakeable,
            Diot(
                args=self._args.args + args + [name],
                kwargs={},
                config=self._args.config,
                popen=self._args.popen,
            ),
        )


class CmdyHolding:
    """Command not running yet"""

    def __new__(cls, args: Diot, bakeable: "Bakeable", will: str = None):

        holding = super().__new__(cls)

        # Use the _onhold function, but fake an object
        if cls._onhold(
            Diot(
                data=Diot(hold=False),
                bakeable=bakeable,
                did="",
                will=will,
            )
        ):
            # __init__ automatically called
            return holding

        holding.__init__(args, bakeable, will)
        result = holding.run()

        if not will:
            return result.wait()

        return result

    def __init__(self, args: Diot, bakeable: "Bakeable", will: str = None):
        # Attach the global EVENT here for later access

        # remember this for resetting
        self._reset_async = args.config["async"]
        self.bakeable = bakeable
        self.shell = args.config.shell
        self.encoding = args.config.encoding
        self.okcode = args.config.okcode
        self.timeout = args.config.timeout
        self.raise_ = args.config["raise"]
        self.should_close_fds = Diot()
        # Should I wait for the results, or just run asyncronouslly
        # This should be controlled by plugins
        # to communicate between each other
        # This only works in sync mode
        self.should_wait = False
        self.did = self.curr = ""
        self.will = will

        # pipes
        self.stdin = subprocess.PIPE
        self.stdout = subprocess.PIPE
        self.stderr = subprocess.PIPE

        args.popen.shell = False

        self.popenargs = args.popen
        # data carried by actions (ie redirect, pipe, etc)
        self.data = Diot({"async": args.config["async"], "hold": False})
        self.cmd = compose_cmd(
            args.args, args.kwargs, args.config, shell=self.shell
        )

    def __repr__(self):
        return f"<CmdyHolding: {self.cmd}>"

    def reset(self):
        """Reset the holding object for reuse"""
        # pipes
        self.stdin = subprocess.PIPE
        self.stdout = subprocess.PIPE
        self.stderr = subprocess.PIPE
        self.did = self.curr = self.will = ""

        self.should_close_fds = Diot()
        self.data = Diot({"async": self._reset_async, "hold": False})
        return self

    @property
    def strcmd(self):
        """Get the stringified cmd"""
        return " ".join(quote(cmdpart) for cmdpart in self.cmd)

    def _run(self):
        try:
            return subprocess.Popen(
                self.cmd,
                stdin=self.stdin,
                stdout=self.stdout,
                stderr=self.stderr,
                **self.popenargs,
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
        return (
            (check_event and self.bakeable._event.is_set())
            or self.data.hold
            or self.will in self.bakeable._holding_left
            or self.did in self.bakeable._holding_right
        )

    @property  # type: ignore
    @property_or_method
    def async_(self):
        """Put command in async mode"""
        if self.data["async"]:
            raise CmdyActionError("Already in async mode.")

        self.data["async"] = True
        # update actions
        self.did, self.curr, self.will = (
            self.curr,
            self.will,
            will(2, raise_exc=False),
        )
        if self._onhold():
            return self
        return self.run()

    a = async_

    @property  # type: ignore
    @property_or_method
    def hold(self):
        """Put the command on hold"""
        # Whever hold is called
        self.data["hold"] = True
        self.did, self.curr, self.will = (
            self.curr,
            self.will,
            will(2, raise_exc=False),
        )

        if self.data["async"] or len(self.data) > 2:
            raise CmdyActionError(
                "Should be called in the first place: .h() or .hold()"
            )
        return self

    h = hold

    def run(self, wait=None):
        """Run the command"""
        if wait is None:
            wait = self.should_wait
        if not self.data["async"]:
            ret = self.bakeable.CmdyResult(self._run(), self)
            if wait:
                return ret.wait()
            return ret

        return self.bakeable.CmdyAsyncResult(self._run(), self)
