import pytest
import sys
import cmdy
from diot import Diot
from cmdy import (cmdy_plugin, cmdy_plugin_add_method, cmdy_plugin_add_property,
                  CmdyHolding, CmdyActionError, _cmdy_hook_class,
                  CmdyAsyncResult, _cmdy_parse_args, STDERR,
                  CMDY_CONFIG, _CMDY_BAKED_ARGS, cmdy_plugin_add_method,
                  cmdy_plugin_hold_then, cmdy_plugin_run_then, cmdy_plugin_async_run_then)
import curio

# testing errors, async and combined use of iter, pipe, redirect
# normal functions are tested in test_cmdy.py

def test_plugin():
    @cmdy_plugin
    class Plugin:
        def method(self):
            pass

    p = Plugin()
    assert p.enabled

    p.disable()
    assert not p.enabled

    p.enable()
    assert p.enabled

def test_add_method_string():

    @cmdy_plugin
    class PluginWithString:
        @cmdy_plugin_add_method("CmdyHolding")
        def _xyz(self):
            return 1

        @cmdy_plugin_add_property("CmdyHolding")
        def _mno(self):
            return 2

        @cmdy_plugin_hold_then
        def xyz(self):
            return self._xyz() + self._mno

    pws = PluginWithString()

    xyz = cmdy.echo().xyz()
    assert xyz == 3

def test_cmdy_plugin_add_method():

    class Base:
        def __init__(self):
            self.base = 1

    _cmdy_hook_class(Base)

    @cmdy_plugin
    class Plugin:
        @cmdy_plugin_add_method(Base)
        def add(self):
            return self.base + 1

    p = Plugin()
    b = Base()
    assert b.add() == 2

    p.disable()
    with pytest.raises(AttributeError):
        b.add()

    # p.enable()
    # assert b.add() == 2

def test_cmdy_plugin_add_method_override():

    class Base:
        def __init__(self):
            self.base = 1

        def add(self):
            return self.base + 10

    _cmdy_hook_class(Base)

    @cmdy_plugin
    class Plugin:
        @cmdy_plugin_add_method(Base)
        def add(self):
            return self._original('add')(self) + 1

    p = Plugin()
    b = Base()
    assert b.add() == 12

    p.disable()
    assert b.add() == 11

    # plugins' enabling/disabling should do before calling
    # p.enable()
    # assert b.add() == 12


def test_cmdy_plugin_add_method_multi_override():

    class Base:
        def __init__(self):
            self.base = 1

        def add(self):
            return self.base + 10

    _cmdy_hook_class(Base)

    @cmdy_plugin
    class Plugin:
        @cmdy_plugin_add_method(Base)
        def add(self):
            return self._original('add')(self) + 1

    @cmdy_plugin
    class Plugin2:
        @cmdy_plugin_add_method(Base)
        def add(self):
            return self._original('add')(self) * 2

    p = Plugin()
    p2 = Plugin2()
    b = Base()
    assert b.add() == 24 # not 22

def test_cmdy_plugin_add_method_multi_override_disable():

    class Base:
        def __init__(self):
            self.base = 1

        def add(self):
            return self.base + 10

    _cmdy_hook_class(Base)

    @cmdy_plugin
    class Plugin:
        @cmdy_plugin_add_method(Base)
        def add(self):
            return self._original('add')(self) + 1

    @cmdy_plugin
    class Plugin2:
        @cmdy_plugin_add_method(Base)
        def add(self):
            return self._original('add')(self) * 2

    b = Base()
    p = Plugin()
    p2 = Plugin2()
    p.disable()
    assert b.add() == 22

def test_cmdy_plugin_add_property():

    class Base:
        def __init__(self):
            self.base = 1
    _cmdy_hook_class(Base)

    @cmdy_plugin
    class Plugin:
        @cmdy_plugin_add_property(Base)
        def base1(self):
            return self.base + 1

    p = Plugin()
    b = Base()
    assert b.base1 == 2

    p.disable()
    with pytest.raises(AttributeError):
        b.base1

    # p.enable()
    # assert b.base1 == 2

def test_cmdy_plugin_add_property_override():

    class Base:
        def __init__(self):
            self.base = 1

        @property
        def base1(self):
            return self.base + 10

    _cmdy_hook_class(Base)

    @cmdy_plugin
    class Plugin:
        @cmdy_plugin_add_property(Base)
        def base1(self):
            return self._original('base1').fget(self) + 1

    p = Plugin()
    b = Base()
    assert b.base1 == 12

    p.disable()
    assert b.base1 == 11

    # p.enable()
    # assert b.base1 == 12

def test_cmdy_plugin_add_property_multi_override():

    class Base:
        def __init__(self):
            self.base = 1

        @property
        def base1(self):
            return self.base + 10

    _cmdy_hook_class(Base)

    @cmdy_plugin
    class Plugin:
        @cmdy_plugin_add_property(Base)
        def base1(self):
            return self._original('base1').fget(self) + 1

    @cmdy_plugin
    class Plugin2:
        @cmdy_plugin_add_property(Base)
        def base1(self):
            return self._original('base1').fget(self) * 2

    p = Plugin()
    p2 = Plugin2()
    b = Base()
    assert b.base1 == 24

def test_cmdy_plugin_add_property_multi_override():

    class Base:
        def __init__(self):
            self.base = 1

        @property
        def base1(self):
            return self.base + 10

    _cmdy_hook_class(Base)

    @cmdy_plugin
    class Plugin:
        @cmdy_plugin_add_property(Base)
        def base1(self):
            return self._original('base1').fget(self) + 1

    @cmdy_plugin
    class Plugin2:
        @cmdy_plugin_add_property(Base)
        def base1(self):
            return self._original('base1').fget(self) * 2

    p = Plugin()
    p2 = Plugin2()
    b = Base()
    p.disable()
    assert b.base1 == 22

def test_hold_then():

    @cmdy_plugin
    class Plugin:
        @cmdy_plugin_hold_then
        def test(self):
            self.stdin = 123
            return self

    assert callable(Plugin.test.enable)
    p = Plugin()
    assert callable(CmdyHolding.test.fget)
    args, kwargs, config, pconfig = _cmdy_parse_args(
        'echo', ['echo', '123'], {},
        CMDY_CONFIG, _CMDY_BAKED_ARGS
    )
    config_copy = CMDY_CONFIG.copy()
    config_copy.update(config)
    h = CmdyHolding(args, kwargs, config_copy, pconfig, will='test').test()
    assert h.stdin == 123

def test_run_then():

    @cmdy_plugin
    class Plugin:
        @cmdy_plugin_run_then
        def ev(self):
            return eval(self.stdout)

    Plugin()
    x = cmdy.echo(n = '{"a": 1}').ev()
    assert x == {"a": 1}


def test_final():
    # cmd = cmdy.echo().h()
    with pytest.raises(CmdyActionError):
        cmdy.echo().h().fg().iter()

def test_run_then_async():

    @cmdy_plugin
    class Plugin:

        @cmdy_plugin_async_run_then('o')
        async def out(self):
            ret = []
            async for line in self:
                ret.append(line.strip())

            return ''.join(ret)

        @cmdy_plugin_async_run_then
        async def list(self):
            ret = []
            async for line in self:
                ret.append(line.strip())
            return ret

    Plugin()

    c = cmdy.echo('1\n2\n3').async_()
    assert isinstance(c, CmdyAsyncResult)

    assert curio.run(c.rc) == 0
    assert curio.run(c.rc) == 0 # trigger self._rc is not None
    out = curio.run(c.out())
    assert out == '123'

    c = cmdy.echo('1\n2\n3').async_()
    clist = curio.run(c.list())
    assert clist == ['1', '2', '3']
    c = cmdy.echo('12 1>&2', cmdy_shell=True).async_().iter(STDERR)
    clist = curio.run(c.list())
    assert clist == ['12']
