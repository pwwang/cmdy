from functools import wraps
from typing import Callable

from varname import will

from .cmdy_exceptions import CmdyActionError
from .cmdy_utils import property_or_method


def _method_enable(cls, names, func):
    for name in names:
        # put original func into stack if any
        stack = cls._plugin_stacks.setdefault(name, [])
        orig_func = getattr(cls, name, None)

        if orig_func:
            stack.insert(0, orig_func)
        setattr(cls, name, func)


def _method_disable(cls, names, func):
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


def _plugin_funcname(func):
    """Get the function name defined in a plugin
    We will ignore the underscores on the right except for those
    magic method, so that we can have the same function defined for
    different classes
    """
    funcname = func.__name__.rstrip("_")
    if funcname.startswith("__"):
        return funcname + "__"
    return funcname


def _add_method(cls: type) -> Callable:
    """A decorator to add a method to a class"""

    def decorator(func):
        func.enable = lambda: _method_enable(
            cls, [_plugin_funcname(func)], func
        )
        func.disable = lambda: _method_disable(
            cls, [_plugin_funcname(func)], func
        )
        return func

    return decorator


def _add_property(cls):
    """A decorator to add a property to a class"""

    def decorator(func):
        func.enable = lambda: _property_enable(
            cls, [_plugin_funcname(func)], func
        )
        func.disable = lambda: _property_disable(
            cls, [_plugin_funcname(func)], func
        )
        return func

    return decorator


def _property_enable(cls, names, func):
    for name in names:
        stack = cls._plugin_stacks.setdefault(name, [])
        orig_prop = getattr(cls, name, None)
        if orig_prop:
            stack.insert(0, orig_prop)
        setattr(cls, name, property(func))


def _property_disable(cls, names, func):
    for name in names:
        curr_prop = getattr(cls, name)
        if curr_prop.fget is func:
            delattr(cls, name)

        cls._plugin_stacks[name] = [
            prop for prop in cls._plugin_stacks[name] if prop.fget is not func
        ]

        if not hasattr(cls, name) and cls._plugin_stacks[name]:
            setattr(cls, name, cls._plugin_stacks[name].pop(0))


def pluginable(cls):
    """Put hooks into the original class for extending"""
    # store the functions with the same name
    # that defined by different plugins
    # Note that current (most recently added) is not in the stack
    cls._plugin_stacks = {}

    def _original(self, fname):
        """Get the original function of self, if it is overridden"""
        # callframe is oringally -1
        frame = self._plugin_callframe.setdefault(fname, -1)
        frame += 1
        self._plugin_callframe[fname] = frame
        # print(cls._plugin_stacks)
        return cls._plugin_stacks[fname][frame]

    cls._original = _original

    orig_init = cls.__init__

    def __init__(self, *args, **kwargs):
        self._plugin_callframe = {}
        orig_init(self, *args, **kwargs)

    cls.__init__ = __init__

    if cls.__name__ == "CmdyHolding":
        orig_reset = cls.reset

        @wraps(orig_reset)
        def reset(self, *args, **kwargs):
            # clear the callframes as well
            self._plugin_callframe = {}
            orig_reset(self, *args, **kwargs)
            return self

        cls.reset = reset

    return cls


class PluginFactory:
    def __init__(
        self,
        bakeable,
    ):
        self.bakeable = bakeable

    def register(self, plugin: type):
        """Register a plugin"""
        orig_init = plugin.__init__  # type: ignore
        data = [
            val for val in plugin.__dict__.values() if hasattr(val, "enable")
        ]

        @wraps(orig_init)
        def __init__(self):
            self.enabled = False
            self.enable()
            orig_init(self)

        def enable(self):
            """Enable all the functions properties defined in the plugin"""
            for val in data:
                val.enable()
            self.enabled = True

        def disable(self):
            """Disable all the functions properties defined in the plugin"""
            for val in data:
                val.disable()
            self.enabled = False

        plugin.enable = enable
        plugin.disable = disable
        plugin.__init__ = __init__  # type: ignore
        return plugin

    def add_method(self, cls: type):
        """Get the add method hook"""
        return _add_method(cls)

    def add_property(self, cls: type):
        """Get the add property hook"""
        return _add_property(cls)

    def _plugin_then(
        self,
        cls,
        func,
        aliases,
        final: bool = False,
        prop: bool = True,
        hold_right: bool = False,
    ) -> Callable:

        aliases = aliases or []
        if not isinstance(aliases, list):
            aliases = [alias.strip() for alias in aliases.split(",")]
        aliases.insert(0, _plugin_funcname(func))

        finals = (
            self.bakeable._holding_finals
            if cls is self.bakeable.CmdyHolding
            else self.bakeable._result_finals
        )

        if final:
            finals.extend(aliases)

        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # Update actions
            self.did, self.curr = self.curr, self.will
            self.will = will(2, raise_exc=False)

            if (
                self.curr in finals
                and self.will in self.bakeable._holding_left
            ):
                raise CmdyActionError("Action taken after a final action.")
            # Initialize data
            # Make it True to tell future actions that I have been called
            # Just in case some plugins forget to do this
            self.data.setdefault(_plugin_funcname(func), {})
            return func(self, *args, **kwargs)

        if prop:
            wrapper.enable = lambda: _property_enable(
                cls, aliases, property_or_method(wrapper)
            )
            wrapper.disable = lambda: _property_disable(
                cls, aliases, property_or_method(wrapper)
            )
        else:
            wrapper.enable = lambda: _method_enable(cls, aliases, wrapper)
            wrapper.disable = lambda: _method_disable(cls, aliases, wrapper)

        if cls is self.bakeable.CmdyHolding:
            self.bakeable._holding_left.extend(aliases)
            if hold_right:
                self.bakeable._holding_right.extend(aliases)

        return wrapper

    def hold_then(
        self,
        alias_or_func=None,
        final: bool = False,
        prop: bool = True,
        hold_right: bool = True,
    ) -> Callable:
        """What to do if a command is holding

        Args:
            alias_or_func (str|list|Callable): Direct decorator or with kwargs
            final (bool): If this is a final action
            prop (bool): Enable the property call for the method
                Only works for CmdyHolding
            hold_right (bool): Tell previous actions that I should be on hold.
                            But make sure running will be taken good care of.
        """

        aliases, func = (
            (None, alias_or_func)
            if callable(alias_or_func)
            else (alias_or_func, None)
        )

        if func:
            return self._plugin_then(
                self.bakeable.CmdyHolding,
                func,
                aliases,
                final=final,
                prop=prop,
                hold_right=hold_right,
            )

        return lambda func: self._plugin_then(
            self.bakeable.CmdyHolding,
            func,
            aliases,
            final=final,
            prop=prop,
            hold_right=hold_right,
        )

    def run_then(
        self,
        alias_or_func=None,
        final: bool = False,
    ) -> Callable:
        """What to do if a command is running"""
        aliases, func = (
            (None, alias_or_func)
            if callable(alias_or_func)
            else (alias_or_func, None)
        )

        if func:
            return self._plugin_then(
                self.bakeable.CmdyResult,
                func,
                aliases,
                final=final,
                prop=False,
            )

        return lambda func: self._plugin_then(
            self.bakeable.CmdyResult,
            func,
            aliases,
            final=final,
            prop=False,
        )
