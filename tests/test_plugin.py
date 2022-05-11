import pytest
import cmdy

import curio
from diot import Diot

from cmdy.cmdy_defaults import get_config
from cmdy.cmdy_plugin import pluginable
from cmdy.cmdy_utils import parse_args

# testing errors, async and combined use of iter, pipe, redirect
# normal functions are tested in test_cmdy.py


def test_plugin():
    bakeable = cmdy()
    @bakeable._plugin_factory.register
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

    bakeable = cmdy()

    @bakeable._plugin_factory.register
    class PluginWithString:
        @bakeable._plugin_factory.add_method(bakeable.CmdyHolding)
        def _xyz(self):
            return 1

        @bakeable._plugin_factory.add_property(bakeable.CmdyHolding)
        def _mno(self):
            return 2

        @bakeable._plugin_factory.hold_then
        def xyz(self):
            return self._xyz() + self._mno

    pws = PluginWithString()

    xyz = bakeable.echo().xyz()
    assert xyz == 3

def test_cmdy_plugin_add_method():
    bakeable = cmdy()

    @pluginable
    class Base:
        def __init__(self):
            self.base = 1

    @bakeable._plugin_factory.register
    class Plugin:
        @bakeable._plugin_factory.add_method(Base)
        def add(self):
            return self.base + 1

    p = Plugin()
    b = Base()
    assert b.add() == 2

    p.disable()
    with pytest.raises(AttributeError):
        b.add()

    p.enable()
    assert b.add() == 2

def test_cmdy_plugin_add_method_override():
    bakeable = cmdy()

    @pluginable
    class Base:
        def __init__(self):
            self.base = 1

        def add(self):
            return self.base + 10

    @bakeable._plugin_factory.register
    class Plugin:
        @bakeable._plugin_factory.add_method(Base)
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
    bakeable = cmdy()
    @pluginable
    class Base:
        def __init__(self):
            self.base = 1

        def add(self):
            return self.base + 10

    @bakeable._plugin_factory.register
    class Plugin:
        @bakeable._plugin_factory.add_method(Base)
        def add(self):
            return self._original('add')(self) + 1

    @bakeable._plugin_factory.register
    class Plugin2:
        @bakeable._plugin_factory.add_method(Base)
        def add(self):
            return self._original('add')(self) * 2

    p = Plugin()
    p2 = Plugin2()
    b = Base()
    assert b.add() == 24 # not 22

def test_cmdy_plugin_add_method_multi_override_disable():
    bakeable = cmdy()

    @pluginable
    class Base:
        def __init__(self):
            self.base = 1

        def add(self):
            return self.base + 10

    @bakeable._plugin_factory.register
    class Plugin:
        @bakeable._plugin_factory.add_method(Base)
        def add(self):
            return self._original('add')(self) + 1

    @bakeable._plugin_factory.register
    class Plugin2:
        @bakeable._plugin_factory.add_method(Base)
        def add(self):
            return self._original('add')(self) * 2

    b = Base()
    p = Plugin()
    p2 = Plugin2()
    p.disable()
    assert b.add() == 22

def test_cmdy_plugin_add_property():
    bakeable = cmdy()
    @pluginable
    class Base:
        def __init__(self):
            self.base = 1

    @bakeable._plugin_factory.register
    class Plugin:
        @bakeable._plugin_factory.add_property(Base)
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
    bakeable = cmdy()
    @pluginable
    class Base:
        def __init__(self):
            self.base = 1

        @property
        def base1(self):
            return self.base + 10

    @bakeable._plugin_factory.register
    class Plugin:
        @bakeable._plugin_factory.add_property(Base)
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
    bakeable = cmdy()
    @pluginable
    class Base:
        def __init__(self):
            self.base = 1

        @property
        def base1(self):
            return self.base + 10

    @bakeable._plugin_factory.register
    class Plugin:
        @bakeable._plugin_factory.add_property(Base)
        def base1(self):
            return self._original('base1').fget(self) + 1

    @bakeable._plugin_factory.register
    class Plugin2:
        @bakeable._plugin_factory.add_property(Base)
        def base1(self):
            return self._original('base1').fget(self) * 2

    p = Plugin()
    p2 = Plugin2()
    b = Base()
    assert b.base1 == 24

def test_cmdy_plugin_add_property_multi_override():
    bakeable = cmdy()

    @pluginable
    class Base:
        def __init__(self):
            self.base = 1

        @property
        def base1(self):
            return self.base + 10

    @bakeable._plugin_factory.register
    class Plugin:
        @bakeable._plugin_factory.add_property(Base)
        def base1(self):
            return self._original('base1').fget(self) + 1

    @bakeable._plugin_factory.register
    class Plugin2:
        @bakeable._plugin_factory.add_property(Base)
        def base1(self):
            return self._original('base1').fget(self) * 2

    p = Plugin()
    p2 = Plugin2()
    b = Base()
    p.disable()
    assert b.base1 == 22

def test_hold_then():
    bakeable = cmdy()
    @bakeable._plugin_factory.register
    class Plugin:
        @bakeable._plugin_factory.hold_then
        def test(self):
            self.stdin = 123
            return self

    assert callable(Plugin.test.enable)
    p = Plugin()
    assert callable(bakeable.CmdyHolding.test.fget)
    args = parse_args(
        'echo', ['echo', '123'], {},
        get_config(), bakeable._baking_args
    )
    config_copy = get_config().copy()
    config_copy.update(args.config)
    h = bakeable.CmdyHolding(
        Diot(args=args.args, kwargs=args.kwargs, config=config_copy, popen=args.popen),
        bakeable,
        will='test',
    ).test()
    assert h.stdin == 123

def test_run_then():
    bakeable = cmdy()

    @bakeable._plugin_factory.register
    class Plugin:
        @bakeable._plugin_factory.run_then
        def ev(self):
            return eval(self.stdout)

    Plugin()
    x = bakeable.echo(n = '{"a": 1}').ev()
    assert x == {"a": 1}


def test_final():
    # cmd = cmdy.echo().h()
    with pytest.raises(cmdy.CmdyActionError):
        cmdy.echo().h().fg().iter()

def test_run_then_async():
    bakeable = cmdy()
    @bakeable._plugin_factory.register
    class Plugin:

        @bakeable._plugin_factory.run_then('o')
        async def out(self):
            ret = []
            async for line in self:
                ret.append(line.strip())

            return ''.join(ret)

        @bakeable._plugin_factory.run_then
        async def list(self):
            ret = []
            async for line in self:
                ret.append(line.strip())
            return ret

    Plugin()

    c = bakeable.echo('1\n2\n3').async_()
    assert isinstance(c, bakeable.CmdyAsyncResult)

    assert curio.run(c.rc) == 0
    assert curio.run(c.rc) == 0 # trigger self._rc is not None
    out = curio.run(c.out())
    assert out == '123'

    c = bakeable.echo('1\n2\n3').async_()
    clist = curio.run(c.list())
    assert clist == ['1', '2', '3']
    c = bakeable.echo('12 1>&2', cmdy_shell=True).async_().iter(bakeable.STDERR)
    clist = curio.run(c.list())
    assert clist == ['12']
