from typing import TYPE_CHECKING, Any

from ..cmdy_defaults import STDIN, STDOUT, STDERR
from ..cmdy_exceptions import CmdyActionError

if TYPE_CHECKING:
    from ..cmdy_bakeable import Bakeable


def vendor(bakeable: "Bakeable"):
    """Vendor the plugins with the bakeable._plugin_factory"""

    @bakeable._plugin_factory.register
    class PluginRedirect:
        """Plugin: redirect
        Redirect the in/out to somewhere else"""

        def _redirect(
            self: bakeable.CmdyHolding,   # type: ignore
            which: list,
            append: bool,
            file: Any,
        ) -> bool:
            # add file-like type suport for file
            if not self.data.get("redirect"):
                raise CmdyActionError(
                    "Cannot redirect a non-redirecting command. "
                    "Did you forget to call .r(), .redir() or .redirect()?"
                )
            curr_pipe = which.pop(0)
            self.data.redirect.which = which

            if curr_pipe == STDIN:
                if isinstance(file, bakeable.CmdyResult):
                    self.stdin = file.proc.stdout
                    self.should_close_fds.stdin = None
                elif hasattr(file, "read"):
                    self.stdin = file
                    self.should_close_fds.stdin = None
                else:
                    self.stdin = open(file, "r", encoding=self.encoding)
                    self.should_close_fds.stdin = self.stdin

            elif curr_pipe == STDOUT:
                if file == STDERR:
                    raise CmdyActionError("Cannot redirect STDOUT to STDERR.")
                if hasattr(file, "read"):
                    self.stdout = file
                    self.should_close_fds.stdout = None
                else:
                    self.stdout = open(
                        file, "a" if append else "w", encoding=self.encoding
                    )
                    self.should_close_fds.stdout = self.stdout
            elif curr_pipe == STDERR:
                if file == STDOUT:
                    self.stderr = STDOUT
                    self.should_close_fds.stderr = None
                elif hasattr(file, "read"):
                    self.stderr = file
                    self.should_close_fds.stderr = None
                else:
                    self.stderr = open(
                        file, "a" if append else "w", encoding=self.encoding
                    )
                    self.should_close_fds.stderr = self.stderr
            else:
                raise CmdyActionError(
                    "Don't know what to redirect. "
                    "Expecting STDIN, STDOUT or STDERR"
                )

            # Since we are holding right, set did to ''
            # to let the right action run
            self.did = ""
            if not which and not self._onhold():
                # self.data.redirect = {}
                return self.run()

            return self

        @bakeable._plugin_factory.add_method(bakeable.CmdyHolding)
        def __gt__(self, file):
            which = self.data.get("redirect", {}).get("which", [STDOUT])
            return PluginRedirect._redirect(self, list(which), False, file)

        @bakeable._plugin_factory.add_method(bakeable.CmdyHolding)
        def __lt__(self, file):
            which = self.data.get("redirect", {}).get("which", [STDOUT])
            return PluginRedirect._redirect(self, list(which), False, file)

        @bakeable._plugin_factory.add_method(bakeable.CmdyHolding)
        def __xor__(self, file):
            """Priority issue with gt (>)
            We need brackets to ensure the order:
            `(cmdy.ls().r(REDIR_RSPT) > outfile) > errfile`
            To avoid this, use xor (^) instead
            """
            which = self.data.get("redirect", {}).get("which", [STDOUT])
            if which[0] == STDIN:
                return self.__lt__(file)
            return self.__gt__(file)

        @bakeable._plugin_factory.add_method(bakeable.CmdyHolding)
        def __rshift__(self, file):
            which = self.data.get("redirect", {}).get("which", [STDOUT])
            return PluginRedirect._redirect(self, list(which), True, file)

        @bakeable._plugin_factory.hold_then("r,redir", hold_right=True)
        def redirect(self, *which):
            """Redirect the input/output"""

            # We should wait for the command to finish, so that we
            # don't leave it piping in background
            # To do so, use it in async mode
            self.should_wait = True

            which = which or [STDOUT]

            # since this is final, so
            # cmdy.ls().r().r() will never happen
            if self.data.redirect:  # pragma: no cover
                raise CmdyActionError("Unconsumed redirect action.")

            # initialize data
            self.data.redirect.which = list(which)

            return self

    return PluginRedirect()
