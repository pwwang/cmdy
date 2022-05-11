from diot import Diot
from .cmdy_defaults import STDOUT, STDERR


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
        if (
            which == STDOUT
            and getattr(result, "_stdout_str", None) is not None
        ):
            return result._stdout_str.splitlines()
        if (
            which == STDERR
            and getattr(result, "_stderr_str", None) is not None
        ):
            return result._stderr_str.splitlines()

        out = result.stdout if which == STDOUT else result.stderr
        if isinstance(out, (str, bytes)):
            return out.splitlines()

        return list(out)

    def __init__(self, result):
        # We cann't do isinstance check for CmdyResult, since it can be from
        # a baked module
        if (
            isinstance(result, Diot)
            or result.__class__.__name__ == "CmdyResult"
        ):

            msgs = [
                f"Unexpected RETURN CODE {result.rc}, "
                f"expecting: {result.holding.okcode}",
                "",
                f"  [   PID] {result.pid}",
                "",
                "  [   CMD] "
                f'{getattr(result, "piped_strcmds", result.cmd)}',
                "",
            ]

            if result.stdout is None:
                msgs.append("  [STDOUT] <NA / ITERATED / REDIRECTED>")
                msgs.append("")
            else:
                outs = CmdyReturnCodeError._out_nowait(result, STDOUT) or [""]
                msgs.append(f"  [STDOUT] {outs.pop().rstrip()}")
                msgs.extend(f"           {out}" for out in outs[:31])
                if len(outs) > 31:
                    msgs.append(f"           [{len(outs)-31} lines hidden.]")
                msgs.append("")

            if result.stderr is None:
                msgs.append("  [STDERR] <NA / ITERATED / REDIRECTED>")
                msgs.append("")
            else:
                errs = CmdyReturnCodeError._out_nowait(result, STDERR) or [""]
                msgs.append(f"  [STDERR] {errs.pop().rstrip()}")
                msgs.extend(f"           {err}" for err in errs[:31])
                if len(errs) > 31:
                    msgs.append(f"           [{len(errs)-31} lines hidden.]")
                msgs.append("")
        else:  # pragma: no cover
            msgs = [str(result)]
        super().__init__("\n".join(msgs))
