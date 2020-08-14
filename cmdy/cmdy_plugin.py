"""Plugins for cmdy"""
from functools import wraps, partial
from varname import will
from .cmdy_util import CmdyActionError, _cmdy_property_or_method

def _cmdy_hook_class(cls):
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
    # self is not a decorator, we don't return cls

def _cmdy_plugin_funcname(func):
    """Get the function name defined in a plugin
    We will ignore the underscores on the right except for those
    magic method, so that we can have the same function defined for
    different classes
    """
    funcname = func.__name__.rstrip('_')
    if funcname.startswith('__'):
        return funcname + '__'
    return funcname

def _raw_plugin(cls):
    """A decorator to define a cmdy plugin
    A cmdy_plugin should be a class and methods
    should be decorated by the hooks
    """
    orig_init = cls.__init__
    data = [val for val in cls.__dict__.values() if hasattr(val, 'enable')]

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

    cls.enable = enable
    cls.disable = disable
    cls.__init__ = __init__
    return cls


def _plugin_then(cls, func, aliases,
                 *, final: bool = False, prop: bool = True,
                 hold_right: bool = False,
                 # we have to pass this for module baking purposes
                 proxy: "_CmdyPluginProxy" = None,
                 ) -> "Callable":

    aliases = aliases or []
    if not isinstance(aliases, list):
        aliases = [alias.strip() for alias in aliases.split(',')]
    aliases.insert(0, _cmdy_plugin_funcname(func))

    finals = (proxy.holding_finals
              if cls is proxy.holding_class
              else proxy.result_finals)
    if final:
        finals.extend(aliases)

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        # Update actions
        self.did, self.curr = self.curr, self.will
        self.will = will(2, raise_exc=False)

        if self.curr in finals and self.will in proxy.holding_left:
            raise CmdyActionError("Action taken after a final action.")
        # Initialize data
        # Make it True to tell future actions that I have been called
        # Just in case some plugins forget to do this
        self.data.setdefault(_cmdy_plugin_funcname(func), {})
        return func(self, *args, **kwargs)

    if prop:
        wrapper.enable = lambda: _cmdy_property_enable(
            cls, aliases, _cmdy_property_or_method(wrapper)
        )
        wrapper.disable = lambda: _cmdy_property_disable(
            cls, aliases, _cmdy_property_or_method(wrapper)
        )
    else:
        wrapper.enable = lambda: _cmdy_method_enable(cls, aliases, wrapper)
        wrapper.disable = lambda: _cmdy_method_disable(cls, aliases, wrapper)

    if cls is proxy.holding_class:
        proxy.holding_left.extend(aliases)
        if hold_right:
            proxy.holding_right.extend(aliases)

    return wrapper

def _raw_add_method(cls):
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

def _raw_add_property(cls):
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


# We can't import the classes here
# If we put them in submodules, plugins will have
# no effects on baked modules
def _raw_hold_then(alias_or_func=None,
                   *, final: bool = False, prop=True,
                   hold_right: bool = True,
                   proxy: "_CmdyPluginProxy" = None):
    """What to do if a command is holding

    Args:
        alias_or_func (str|list|Callable): Direct decorator or with kwargs
        final (bool): If this is a final action
        prop (bool): Enable the property call for the method
            Only works for CmdyHolding
        hold_right (bool): Tell previous actions that I should be on hold.
                        But make sure running will be taken good care of.
    """
    aliases = None if callable(alias_or_func) else alias_or_func
    func = alias_or_func if callable(alias_or_func) else None

    if func:
        return _plugin_then(proxy.holding_class, func, aliases,
                            final=final, prop=prop, hold_right=hold_right,
                            proxy=proxy)

    return lambda func: _plugin_then(
        proxy.holding_class, func, aliases,
        final=final, prop=prop, hold_right=hold_right,
        proxy=proxy
    )

def _raw_run_then(alias_or_func=None, *, final: bool = False,
                  proxy: "_CmdyPluginProxy" = None):
    """What to do when a command is running"""
    aliases = None if callable(alias_or_func) else alias_or_func
    func = alias_or_func if callable(alias_or_func) else None

    if func:
        return _plugin_then(proxy.result_class, func, aliases,
                            final=final, prop=False, proxy=proxy)

    return lambda func: _plugin_then(
        proxy.result_class, func, aliases,
        final=final, prop=False, proxy=proxy
    )

def _raw_async_run_then(alias_or_func=None, *, final: bool = False,
                        proxy: "_CmdyPluginProxy" = None):
    """What to do when a command is running asyncronously"""
    aliases = None if callable(alias_or_func) else alias_or_func
    func = alias_or_func if callable(alias_or_func) else None

    if func:
        return _plugin_then(proxy.async_result_class, func, aliases,
                            final=final, prop=False, proxy=proxy)

    return lambda func: _plugin_then(
        proxy.async_result_class, func, aliases,
        final=final, prop=False, proxy=proxy
    )

class _CmdyPluginProxy:
    """Wrap all stuff that are needed by main module.
    We can't define them directly, because of module baking
    We need to pass in the unique values/variables that used in
    original and baked module. So that this submodule can be reused.
    """
    def __init__(self,
                 holding_class,
                 result_class,
                 async_result_class,
                 holding_left,
                 holding_right,
                 holding_finals,
                 result_finals):
        self.holding_class = holding_class
        self.result_class = result_class
        self.async_result_class = async_result_class
        self.holding_left = holding_left
        self.holding_right = holding_right
        self.holding_finals = holding_finals
        self.result_finals = result_finals
        self._classmap = {
            'CmdyHolding': self.holding_class,
            'CmdyResult': self.result_class,
            'CmdyAsyncResult': self.async_result_class
        }

    def hook_plugin(self):
        """Get the plugin class hook"""
        return _raw_plugin

    def hook_add_method(self):
        """Get the add method hook"""
        def wrapper(cls):
            if isinstance(cls, str):
                cls = self._classmap[cls]
            return _raw_add_method(cls)

        return wrapper

    def hook_add_property(self):
        """Get the add property hook"""
        def wrapper(cls):
            if isinstance(cls, str):
                cls = self._classmap[cls]
            return _raw_add_property(cls)

        return wrapper

    def hook_hold_then(self):
        """Get the hold then hook"""
        return partial(_raw_hold_then, proxy=self)

    def hook_run_then(self):
        """Get the run then hook"""
        return partial(_raw_run_then, proxy=self)

    def hook_async_run_then(self):
        """Get the async run then hook"""
        return partial(_raw_async_run_then, proxy=self)
