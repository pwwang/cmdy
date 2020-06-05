"""Plugins for cmdy"""
from functools import wraps
from varname import will
from .cmdy_util import CmdyActionError

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

    # Not doing isinstance checking for module baking purposes
    if cls.__name__ == 'CmdyHolding':
        orig_reset = cls.reset
        def reset(self, *args, **kwargs):
            # clear the callframes as well
            self._plugin_callframe = {}
            orig_reset(self, *args, **kwargs)
            return self

        cls.reset = reset
    # this is not a decorator, we don't return cls

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

def _plugin_then(cls, func, aliases,
                 # we have to pass this for module baking purposes
                 holding_finals: list, result_finals: list,
                 holding_left: list, holding_right: list,
                 *, final: bool = False, hold_right: bool = False
                 ) -> "Callable":
    aliases = aliases or []
    if not isinstance(aliases, list):
        aliases = [alias.strip() for alias in aliases.split(',')]
    aliases.insert(0, _cmdy_plugin_funcname(func))

    finals = (holding_finals
              if cls.__name__ == 'CmdyHolding'
              else result_finals)
    if final:
        finals.extend(aliases)

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        # Update actions
        self.did, self.curr, self.will = self.curr, self.will, will()

        if self.curr in finals and self.will in holding_left:
            raise CmdyActionError("Action taken after a final action.")
        # Initialize data
        # Make it True to tell future actions that I have been called
        # Just in case some plugins forget to do this
        self.data.setdefault(_cmdy_plugin_funcname(func), {})
        return func(self, *args, **kwargs)

    wrapper.enable = lambda: _cmdy_method_enable(cls, aliases, wrapper)
    wrapper.disable = lambda: _cmdy_method_disable(cls, aliases, wrapper)

    if cls.__name__ == 'CmdyHolding':
        holding_left.extend(aliases)
        if hold_right:
            holding_right.extend(aliases)
    return wrapper

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
