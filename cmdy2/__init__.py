import sys
from .module import CmdyModule as _CmdyModule


sys.modules[__name__] = _CmdyModule(__name__)
