from typing import TYPE_CHECKING

from curio import subprocess

from ..cmdy_defaults import STDOUT, STDERR
from ..cmdy_exceptions import CmdyActionError

if TYPE_CHECKING:
    from ..cmdy_bakeable import Bakeable


def vendor(bakeable: "Bakeable"):
    """Vendor the plugins with the bakeable._plugin_factory"""

    @bakeable._plugin_factory.register
    class PluginPipe:
        """Plugin: pipe
        Allow piping from one command to another
        `cmdy.ls().pipe() | cmdy.cat()`
        """

        @bakeable._plugin_factory.add_property(bakeable.CmdyResult)
        def piped_cmds(self):
            """Get cmds that along the piping path

            Example:
                ```python
                c = cmdy.echo(123).p() | cmdy.cat()
                c.piped_cmds == ['echo 123', 'cat']
                ```
            """
            piped_from = self.holding.data.get("pipe", {}).get("from")
            if piped_from:
                return piped_from.piped_cmds + [self.cmd]
            return [self.cmd]

        @bakeable._plugin_factory.add_property(bakeable.CmdyResult)
        def piped_strcmds(self):
            """Get cmds that along the piping path

            Example:
                ```python
                c = cmdy.echo(123).p() | cmdy.cat()
                c.piped_cmds == ['echo 123', 'cat']
                ```
            """
            piped_from = self.holding.data.get("pipe", {}).get("from")
            if piped_from:
                return piped_from.piped_strcmds + [self.strcmd]
            return [self.strcmd]

        @bakeable._plugin_factory.add_property(bakeable.CmdyHolding)
        def piped_cmds_(self):
            """Get cmds that along the piping path

            Example:
                ```python
                c = cmdy.echo(123).p() | cmdy.cat()
                c.piped_cmds == ['echo 123', 'cat']
                ```
            """
            piped_from = self.data.get("pipe", {}).get("from")
            if piped_from:
                return piped_from.piped_cmds + [self.cmd]
            return [self.cmd]

        @bakeable._plugin_factory.add_property(bakeable.CmdyHolding)
        def piped_strcmds_(self):
            """Get cmds that along the piping path

            Example:
                ```python
                c = cmdy.echo(123).p() | cmdy.cat()
                c.piped_cmds == ['echo 123', 'cat']
                ```
            """
            piped_from = self.data.get("pipe", {}).get("from")
            if piped_from:
                return piped_from.piped_strcmds + [self.strcmd]
            return [self.strcmd]

        @bakeable._plugin_factory.add_method(bakeable.CmdyHolding)
        def __or__(
            self,
            other: bakeable.CmdyHolding,  # type: ignore
        ):

            if not self.data.get("pipe"):
                raise CmdyActionError(
                    "Piping options have been consumed or trying "
                    "to pipe from non-piping command"
                )

            assert isinstance(other, bakeable.CmdyHolding), (
                "Can only pipe to " "a CmdyHolding object."
            )

            other_pipe_data = other.data.setdefault("pipe", {})
            other_pipe_data["from"] = self

            # We shall not check the event, because the purpose here
            # is to clear the EVENT
            # But we need to check if other is also a piping command
            # which will be set if .pipe() is called
            if not other._onhold(check_event=False) and not other.data.get(
                "pipe", {}
            ).get("which"):
                self.bakeable._event.clear()
                return other.run()

            return other

        @bakeable._plugin_factory.hold_then("p")
        def pipe(self, which=None):
            """Allow command piping"""
            if self.data.get("pipe"):
                raise CmdyActionError("Unconsumed piping action.")

            # initialize data
            which = which or STDOUT
            self.data.pipe.which = which

            if (which == STDOUT and self.stdout != subprocess.PIPE) or (
                which == STDERR and self.stderr != subprocess.PIPE
            ):

                raise CmdyActionError("Cannot pipe from a redirected PIPE.")
            self.bakeable._event.set()
            return self

        @bakeable._plugin_factory.add_method(bakeable.CmdyHolding)
        def run(self, wait=None):
            """From from prior piped command"""
            orig_run = self._original("run")

            if not self.data.get("pipe", {}).get("from"):
                return orig_run(self, wait)

            prior = self.data.pipe["from"]
            prior_result = prior.run(False)
            self.data.pipe["from"] = prior

            self.stdin = (
                prior_result.proc.stdout
                if prior.data.pipe.which == STDOUT
                else prior_result.proc.stderr
            )

            ret = orig_run(self, wait)
            prior_result.wait()
            return ret

    return PluginPipe()
