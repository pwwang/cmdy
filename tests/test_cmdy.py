import sys
import tempfile
from path import Path
from contextlib import contextmanager
from diot import Diot
import pytest
import cmdy
from cmdy import (CmdyHolding, _CMDY_EVENT, _cmdy_parse_args, CmdyResult,
                  CmdyBakingError, STDOUT, STDERR, STDIN, DEVNULL,
                  CMDY_PLUGIN_ITER,
                  CmdyActionError, CmdyAsyncResult, CmdyTimeoutError,
                  CmdyReturnCodeError, CmdyExecNotFoundError)
import curio

def teardown_function():
    _CMDY_EVENT.clear()

@pytest.fixture
def no_iter():
    CMDY_PLUGIN_ITER.disable()
    yield
    CMDY_PLUGIN_ITER.enable()

@pytest.fixture
def captured():

    @contextmanager
    def wrapper():
        tmpfile = tempfile.NamedTemporaryFile('w', delete=False)
        old_stdout = sys.stdout
        sys.stdout = tmpfile

        yield Path(tmpfile.name), tmpfile
        sys.stdout.close()
        sys.stdout = old_stdout
    return wrapper

def test_holding_new():

    ret = CmdyHolding(*_cmdy_parse_args('echo', ['echo', '123'], {}))
    assert isinstance(ret, CmdyResult)

def test_normal_run():

    ret = cmdy.echo(n='1')
    assert ret == '1'
    assert ret.rc == ret._rc == 0

    ret = cmdy.echo('1')
    assert ret.strip() == '1'
    assert ret.rc == 0
    ret._stderr = 12
    assert ret.stderr == 12

def test_bake():

    echo = cmdy.echo(n=True).bake()
    ret = echo(_='1')
    assert ret.cmd == ['echo', '-n', '1']
    assert ret == '1'

    with pytest.raises(CmdyBakingError):
        cmdy.echo('1').bake()

def test_fg(capsys):
    # use a file obj to replace sys.stdout
    # capsys doesn't work here
    c = cmdy.echo('123').fg()
    assert isinstance(c, CmdyResult)
    assert capsys.readouterr().out == '123\n'

def test_fg_hold_right(capsys):

    c = cmdy.bash(c='echo 1234 && sleep .1').p() | cmdy.cat().fg()
    assert isinstance(c, CmdyResult)
    assert capsys.readouterr().out == '1234\n'

def test_fg_warning():
    h = cmdy.echo(123).h()
    h.stdout = 99
    with pytest.warns(UserWarning):
        h.fg().run()

def test_fg_noencoding(capsysbinary):
    cmdy.echo(123, cmdy_encoding=None).fg()
    assert capsysbinary.readouterr().out == b'123\n'

def test_fg_timeout(capsys):
    cmdy.bash(c='sleep .2 && echo 123').fg()
    assert capsys.readouterr().out == '123\n'

def test_redirect(tmp_path):

    tmpfile = tmp_path / 'test_redirect.txt'
    c = cmdy.echo(n='1234').r() > tmpfile
    assert tmpfile.read_text() == '1234'
    assert c.holding.stdout.closed
    assert c.stdout is None
    assert c.stderr == ''

def test_redirect_failing_fetching(no_iter):
    c = cmdy.echo(n=123).r(STDOUT) > DEVNULL
    assert c.holding.stdout != curio.subprocess.PIPE
    assert c.stdout is None

    c = cmdy.bash(c='echo 123 1>&2').r(STDERR) > DEVNULL
    assert c.stderr is None

def test_redirect_stdin(tmp_path):
    tmpfile = tmp_path / 'test_redirect_stdin.txt'
    tmpfile.write_text('1\n2\n3')
    c = cmdy.cat().r(STDIN) < tmpfile
    assert c == '1\n2\n3'

    c = cmdy.cat().r(STDIN) < cmdy.cat(tmpfile)
    assert c == '1\n2\n3'

    # from filelike
    with open(tmpfile, 'r') as f:
        c = cmdy.cat().r(STDIN) < f
    assert c == '1\n2\n3'

def test_redirect_rspt(tmp_path):
    outfile = tmp_path / 'test_redirect_respectively_out.txt'
    errfile = tmp_path / 'test_redirect_respectively_err.txt'
    c = cmdy.echo(
        '-n 123 1>&2 && echo -n 456', cmdy_shell=True
    ).r(STDOUT, STDERR) ^ outfile > errfile
    assert outfile.read_text() == '456'
    assert errfile.read_text() == '123'

    with open(outfile, 'a') as fout, open(errfile, 'w') as ferr:
        c = cmdy.echo(
            '-n 123 1>&2 && echo -n 456', cmdy_shell=True
        ).r(STDOUT, STDERR) ^ fout > ferr
        # fh should not be closed
        fout.write('78')

    assert outfile.read_text() == '45645678'
    assert errfile.read_text() == '123'



def test_redirect_both(tmp_path):
    outfile = tmp_path / 'test_redirect_both_out.txt'
    c = cmdy.echo(
        '-n 123 1>&2 && echo -n 456', cmdy_shell=True
    ).r(STDERR, STDOUT) ^ STDOUT > outfile
    assert outfile.read_text() == '123456'

    c = cmdy.echo(
        '-n 123 1>&2 && echo -n 456', cmdy_shell=True
    ).r(STDOUT, STDERR) >> outfile > STDOUT
    assert outfile.read_text() == '123456123456'
    assert c.stdout is None

def test_redirect_mixed(tmp_path):
    infile = tmp_path / 'test_redirect_mixed.txt'
    outfile = tmp_path / 'test_redirect_mixed_out.txt'
    infile.write_text('123')
    cmdy.cat().r(STDIN, STDOUT) ^ infile > outfile
    assert outfile.read_text() == '123'

def test_redirect_stderr(tmp_path):
    tmpfile = tmp_path / 'test_redirect_stderr.txt'
    c = cmdy.echo('1234 1>&2', cmdy_shell=True).r(STDERR) > tmpfile
    assert tmpfile.read_text() == '1234\n'
    assert c.stderr is None

    tmpfile2 = tmp_path / 'test_redirect_stdout.txt'
    c = cmdy.echo('1234 1>&2', cmdy_shell=True).r(STDOUT) > tmpfile2
    assert tmpfile2.read_text() == ''

def test_hold(tmp_path):

    tmpfile = tmp_path / 'test_redirect.txt'
    c = cmdy.echo(n='1234').h()
    cmd = c.r() > tmpfile
    cmd.run()
    assert tmpfile.read_text() == '1234'

def test_hold_then_iter():
    c = cmdy.echo('1\n2\n3').h()
    ret = []
    for line in c.run().iter():
        ret.append(line.strip())
    assert ret == ['1', '2', '3']

def test_pipe():

    c = cmdy.echo("1\n2\n3").p() | cmdy.grep(2)
    assert c == '2\n'

def test_multi_pipe():
    c = cmdy.echo("11\n12\n22\n23").p() | cmdy.grep(2).p() | cmdy.grep(22)
    assert c == '22\n'

def test_iter():
    c = cmdy.echo("1\n2\n3").iter()
    assert next(c) == '1\n'
    assert next(c) == '2\n'
    assert next(c) == '3\n'

    assert c.rc == 0

    with pytest.raises(StopIteration):
        next(c)

    c = cmdy.echo("1\n2\n3").iter()
    ret = []
    for line in c:
        ret.append(line.strip())
    assert ret == ['1', '2', '3']

def test_iter_stderr():
    c = cmdy.echo("123 1>&2", cmdy_shell=True).iter(STDERR)
    ret = []
    for line in c:
        ret.append(line.strip())
    assert ret == ['123']

def test_module_baking():
    sh = cmdy(n=True)
    assert id(sh._CMDY_EVENT) != id(_CMDY_EVENT)
    assert id(sh._CMDY_BAKED_ARGS) != id(cmdy._CMDY_BAKED_ARGS)
    assert sh.Cmdy('echo')(_=123).strcmd == 'echo -n 123'
    assert cmdy.echo(123).strcmd == 'echo 123'

    # test event blocking
    cmdy.echo().p()
    assert cmdy._CMDY_EVENT.is_set()
    assert not sh._CMDY_EVENT.is_set()
    c = cmdy.echo() # suppose to run but locked
    assert isinstance(c, CmdyHolding)
    c = sh.echo() # ran
    assert isinstance(c, sh.CmdyResult)

    sh2 = sh(e=True)
    c = sh2.echo(_=1).h()
    assert c.strcmd == 'echo -n -e 1'

    assert (sh.CmdyExecNotFoundError == sh2.CmdyExecNotFoundError ==
            CmdyExecNotFoundError)

    with pytest.raises(CmdyExecNotFoundError):
        sh2.nonexisting()


def test_subcommand():
    assert cmdy.echo.a() == 'a\n'

def test_timeout():
    with pytest.raises(CmdyTimeoutError):
        cmdy.sleep(.5, cmdy_timeout=.1)
    # runs ok
    cmdy.sleep(.1, cmdy_timeout=.5)

def test_pid():
    assert isinstance(cmdy.echo().pid, int)

def test_returncode_error():

    with pytest.raises(CmdyReturnCodeError):
        cmdy.bash('exit', 1)

def test_exenotfound_error():

    with pytest.raises(CmdyExecNotFoundError):
        cmdy._no_such_command()

def test_full_rc_error():
    # stderr redirected
    with pytest.raises(CmdyReturnCodeError) as ex:
        cmdy.bash.exit(1).r(STDERR) > DEVNULL
    assert '[STDERR] <NA / ITERATED / REDIRECTED>' in str(ex.value)

    # long stdout
    with pytest.raises(CmdyReturnCodeError) as ex:
        cmdy.echo('-e "' + '\n'.join(str(s) for s in range(40)) + '" && exit 1',
                  cmdy_shell=True)
    assert '[8 lines hidden.]' in str(ex.value)

    # long stderr
    with pytest.raises(CmdyReturnCodeError) as ex:
        cmdy.echo('-e "' + '\n'.join(str(s) for s in range(40)) + '" 1>&2 && exit 1',
                  cmdy_shell=True)
    assert '[8 lines hidden.]' in str(ex.value)

def test_line_fetch_timeout():

    import time
    c = cmdy.bash(c='echo 1; sleep .21; echo 2').iter()
    time.sleep(.1)
    assert c.next(timeout=.1) == '1\n'
    assert c.next(timeout=.1) == ''
    assert c.next(timeout=.1) == '2\n'

def test_piped_cmds():
    c = cmdy.echo(123).p() | cmdy.cat().r() ^ DEVNULL
    assert c.piped_cmds == [['echo', '123'], ['cat']]
    assert c.piped_strcmds == ['echo 123', 'cat']

    # works on holding objects too
    c = cmdy.echo(123).p() | cmdy.cat().h()
    assert c.piped_strcmds == ['echo 123', 'cat']
    assert c.piped_cmds == [['echo', '123'], ['cat']]

    assert cmdy.echo(123).piped_cmds == [['echo', '123']]
    assert cmdy.echo(123).piped_strcmds == ['echo 123']
    _CMDY_EVENT.clear()
    c = cmdy.echo(123)
    assert isinstance(c, CmdyResult)
    assert c.piped_cmds == [['echo', '123']]

def test_reprs():
    c = cmdy.echo(123).h()
    assert repr(c) == "<CmdyHolding: ['echo', '123']>"

    c = cmdy.echo(123)
    assert repr(c) == "<CmdyResult: ['echo', '123']>"

    c = cmdy.echo(123).a()
    assert repr(c) == "<CmdyAsyncResult: ['echo', '123']>"

def test_reset():
    c = cmdy.echo(n=123).h().r(STDOUT) > DEVNULL
    c = c.run(True)
    assert isinstance(c, CmdyResult)
    assert c.stdout is None # redirected

    reuse = c.holding.reset().run(True)
    assert isinstance(reuse, CmdyResult)
    assert reuse.stdout == '123'


def test_async_close_fd(tmp_path):
    tmpfile = tmp_path / 'test_async_close_fd.txt'
    c = cmdy.echo(n="123").async_().r(STDOUT) > tmpfile
    curio.run(c.wait())
    assert c.holding.stdout.closed

def test_async_fg(tmp_path):
    c = cmdy.echo(n="").async_().fg()
    assert isinstance(c, cmdy.CmdyAsyncResult)

def test_async_timeout():
    c = cmdy.sleep(.5, cmdy_timeout=.1).a()
    with pytest.raises(CmdyTimeoutError):
        curio.run(c.wait())

    # runs ok
    curio.run(cmdy.sleep(.1, cmdy_timeout=.5).a().wait())


def test_async_value():
    c = cmdy.echo(n=123).async_()
    async def get_value():
        return (await c.astr(), await c.aint(), await c.afloat())

    assert curio.run(get_value()) == ('123', 123, 123.0)

def test_async_value_redirect_error():
    c = cmdy.echo(n=123).async_().r(STDOUT) > DEVNULL
    assert isinstance(c, CmdyAsyncResult)
    with pytest.raises(CmdyActionError):
        curio.run(c.astr())

def test_async_value_stderr():
    c = cmdy.echo('-n 123 1>&2', cmdy_shell=True).a()
    curio.run(c.wait())
    assert curio.run(c.astr(STDERR)) == '123'

    c = cmdy.echo('-n 123 1>&2', cmdy_encoding=None, cmdy_shell=True).a()
    assert curio.run(c.astr(STDERR)) == b'123'
    assert curio.run(c.astr(STDERR)) == b'123' # trigger cache

    with pytest.raises(CmdyActionError):
        curio.run(c.astr(111))


def test_pipe_error():

    with pytest.raises(cmdy.CmdyActionError):
        cmdy.cat().h() | cmdy.grep(cmdy_raise=False)

    h = cmdy.cat().h()
    h.stdout = sys.stderr
    with pytest.raises(cmdy.CmdyActionError):
        h.p() | cmdy.grep()

def test_redirect_error():
    with pytest.raises(CmdyActionError):
        cmdy.echo(123).h() > 1
    with pytest.raises(CmdyActionError):
        cmdy.echo().r('a') > 1

def test_redirect_err_to_stdout():
    with pytest.raises(CmdyActionError):
        cmdy.echo().r(STDOUT) > STDERR

    c = cmdy.echo('-n 123 1>&2', cmdy_shell=True).r(STDERR) > STDOUT
    assert c == '123'
    c = cmdy.echo('-n 123 1>&2', cmdy_shell=True)
    assert c.str(STDERR) == '123'
    assert c.str(STDERR) == '123'

def test_iter_from_redirect():

    c = cmdy.echo('-n 123 1>&2', cmdy_shell=True).r(STDERR) > STDOUT
    ret = []
    for line in c.iter():
        ret.append(line.strip())
    assert ret == ['123']

def test_iter_from_redirect_error():

    c = cmdy.echo('-n 123 1>&2', cmdy_shell=True).r(STDERR) > STDOUT
    with pytest.raises(CmdyActionError):
        c.iter(STDERR)

def test_str(no_iter):
    c = cmdy.echo(n=123).str()
    assert c == '123'

    c = cmdy.echo(n=123)
    assert str(c) == '123'
    assert '1' in c
    assert c != '1'
    assert c.stdout == '123'
    assert c.stdout == '123' # trigger cache

    c = cmdy.echo(n=',')
    assert c.join(['1', '2']) == '1,2'

    assert cmdy.echo(n=123).int() == 123
    assert cmdy.echo(n=123).float() == 123.0

    with pytest.raises(AttributeError):
        cmdy.echo(n=123).x()

def test_str_error():

    c = cmdy.echo(n=123).r(STDOUT) > DEVNULL
    with pytest.raises(CmdyActionError):
        c.str()

    with pytest.raises(CmdyActionError):
        cmdy.echo(n=123).str('xyz')


def test_str_from_stderr(no_iter):
    c = cmdy.bash(c='echo -n 123 1>&2')
    assert c.int(STDERR) == 123
    assert c.stderr == '123'
    assert c.stderr == '123' # trigger cache

def test_str_from_iter():

    c = cmdy.echo('-n 123 1>&2', cmdy_shell=True).iter(STDERR)
    assert c.str(STDERR) == '123'

def test_redirect_then_iter(tmp_path):

    #c = cmdy.echo('-n 123 1>&2', cmdy_shell=True).r(STDERR).h() > STDOUT
    # the right way:
    c = cmdy.echo('-n 123 1>&2', cmdy_shell=True).h()
    r = c.r(STDERR) > STDOUT
    assert list(r.run().iter()) == ['123']

    tmpfile = tmp_path / 'test_redirect_then_iter.txt'
    c = cmdy.echo(n=123).h()
    c.stdout = tmpfile.open('w')
    c.stderr = tmpfile.open('w')
    r = c.run()
    r.data.iter = Diot(which=STDOUT)
    assert r.stdout is None
    assert r.stderr is None

def test_async_rc_error():
    c = cmdy.bash('exit', '1').a()
    assert isinstance(c, CmdyAsyncResult)
    with pytest.raises(CmdyReturnCodeError):
        curio.run(c.wait())

def test_raise_from_iter():
    c = cmdy.echo('1 && exit 1', cmdy_shell=True, cmdy_okcode='0').iter()
    with pytest.raises(CmdyReturnCodeError):
        for line in c:
            pass

def test_raise_from_redirect():
    #c = cmdy.echo('1 && exit 1', cmdy_shell=True).r(STDOUT).h() > DEVNULL
    # the right way:
    c = cmdy.echo('1 && exit 1', cmdy_shell=True).h()

    c.r(STDOUT) > DEVNULL
    with pytest.raises(CmdyReturnCodeError) as ex:
        c.run()
    assert '[STDOUT] <NA / ITERATED / REDIRECTED>' in str(ex.value)

def test_iter_stdout_dump_stderr():
    c = cmdy.echo(n=1).iter()
    assert list(c) == ['1']
    assert c.stderr == ''

    c._stdout = 1
    with pytest.raises(TypeError):
        next(c)

def test_iter_stderr_dump_stdout():
    c = cmdy.echo('-n 1 1>&2', cmdy_shell=True).iter(STDERR)
    assert list(c) == ['1']
    assert c.stdout == ''

    c._stderr = 1
    with pytest.raises(TypeError):
        next(c)

def test_mixed_actions_hold_then():
    # actions could be
    # hold
    # async_
    # redirect
    # fg
    # iter
    # pipe
    a = cmdy.echo(123).h().a()
    assert isinstance(a, CmdyHolding)

    r = cmdy.echo(123).h().r()
    assert isinstance(r, CmdyHolding)

    fg = cmdy.echo(123).h().fg()
    assert isinstance(fg, CmdyHolding)

    it = cmdy.echo(123).h().iter()
    assert isinstance(it, CmdyHolding)

    p = cmdy.echo(123).h().p()
    # release the lock
    _CMDY_EVENT.clear()
    assert isinstance(p, CmdyHolding)

    c = cmdy.echo(123).h()
    a = c.a()
    assert isinstance(a, CmdyHolding)
    assert isinstance(a.run(), CmdyAsyncResult)

    c = cmdy.echo(123).h()
    r = c.r() > DEVNULL
    assert isinstance(r, CmdyHolding)
    assert isinstance(r.run(), CmdyResult)

    c = cmdy.echo(123).h()
    r = c.fg()
    assert isinstance(r, CmdyHolding)
    assert isinstance(r.run(), CmdyResult)

    c = cmdy.echo(123).h()
    r = c.iter()
    assert isinstance(r, CmdyHolding)
    assert isinstance(r.run(), CmdyResult)

    c = cmdy.echo(123).h()
    r = c.p()
    assert isinstance(r, CmdyHolding)
    assert _CMDY_EVENT.is_set()

def test_mixed_actions_async_then():
    # actions could be
    # hold
    # async_
    # redirect
    # fg
    # iter
    # pipe

    with pytest.raises(CmdyActionError):
        # Unnecessary hold before an action.
        cmdy.echo().a().h()

    with pytest.raises(CmdyActionError):
        cmdy.echo().a().a()

    c = cmdy.echo().a()
    with pytest.raises(AttributeError):
        c.h()

    with pytest.raises(AttributeError):
        c.a()

    a = cmdy.echo('1 1>&2', cmdy_shell=True).a().r(STDERR) > STDOUT
    assert isinstance(a, CmdyAsyncResult)

    c = cmdy.echo('1 1>&2', cmdy_shell=True).h()
    assert isinstance(c.a().run(), CmdyAsyncResult)

    a = cmdy.echo().a().fg()
    assert isinstance(a, CmdyAsyncResult)

    it = cmdy.echo().a().iter()
    assert isinstance(it, CmdyAsyncResult)

    it = cmdy.echo().h().a().run().iter()
    assert isinstance(it, CmdyAsyncResult)

    c = cmdy.echo().a().p()
    _CMDY_EVENT.clear()
    assert isinstance(c, CmdyHolding)

def test_mixed_actions_async_then_fg():
    c = cmdy.echo().h()
    fg = c.a().fg().run()
    assert isinstance(fg, CmdyAsyncResult)

def test_mixed_actions_async_then_pipe():
    c = cmdy.echo().h()
    assert isinstance(c, CmdyHolding)
    p = c.a().p().run()
    assert isinstance(p, CmdyAsyncResult)

def test_mixed_actions_redir_then():
    # actions could be
    # hold
    # async_
    # redirect
    # fg
    # iter
    # pipe
    with pytest.raises(CmdyActionError):
        cmdy.echo().r().h()

    r = cmdy.echo().r()
    with pytest.raises(CmdyActionError):
        r.h()

    a = cmdy.echo().r().a()
    assert isinstance(a, CmdyHolding)

    h = cmdy.echo().h()
    x = h.r().a().run()
    assert isinstance(x, CmdyAsyncResult)

    with pytest.raises(CmdyActionError):
        cmdy.echo().r().r()

    r = cmdy.echo().r()
    with pytest.raises(CmdyActionError):
        r.r()

    h = cmdy.echo().h()
    with pytest.raises(CmdyActionError):
        r.r().r()

    r = cmdy.echo().r() > DEVNULL
    with pytest.raises(AttributeError):
        r.fg()


    c = cmdy.echo().r().pipe()
    assert isinstance(c, CmdyHolding)

def test_mixed_actions_redir_then_fg():
    with pytest.warns(UserWarning) as w:
        c = cmdy.echo(123).r().fg() > DEVNULL
    assert isinstance(c, CmdyResult)
    assert c.stdout == ''
    assert str(w.pop().message) == 'Previous redirected pipe will be ignored.'

def test_mixed_actions_fg_then():
    # actions could be
    # hold
    # async_
    # redirect
    # fg
    # iter
    # pipe

    # fg is final, cannot do anything else
    with pytest.raises(CmdyActionError):
        cmdy.echo().h().fg().r()

def test_mixed_actions_iter_then():

    # iter is also final
    with pytest.raises(CmdyActionError):
        cmdy.echo().h().iter().r()

def test_mixed_actions_pipe_then():
    # actions could be
    # hold
    # async_
    # redirect
    # fg
    # iter
    # pipe
    c = cmdy.echo().h().pipe().r()
    assert isinstance(c, CmdyHolding)
    _CMDY_EVENT.clear()

    with pytest.raises(CmdyActionError):
        cmdy.echo().p().h()

    c = cmdy.echo().p().a()
    assert isinstance(c, CmdyHolding)
    _CMDY_EVENT.clear()

    c = cmdy.bash(c='echo "1\n2\n3" 1>&2').p().r(STDERR) ^ STDOUT | cmdy.grep(2)
    assert c.str() == '2\n'

    with pytest.raises(CmdyActionError) as ex:
        cmdy.echo().p().p()
    assert 'Unconsumed piping' in str(ex.value)

def test_mixed_actions_pipe_then_fg(capsys):

    c = cmdy.bash(
        c='echo 123 1>&2 && echo 456'
    ).p(STDERR).fg() | cmdy.grep(4, cmdy_okcode='0,1')
    assert capsys.readouterr().out == '456\n'
    assert c.str() == '' # have been redirected by fg

def test_mixed_actions_pipe_then_iter(capsys):
    c = cmdy.bash(
        c='echo "1\n2\n3" 1>&2'
    ).p(STDERR).iter(STDOUT)
    d = c | cmdy.grep(2, cmdy_okcode='0,1')
    assert isinstance(d, CmdyResult)
    assert isinstance(c, CmdyHolding)
    assert d == '2\n'


