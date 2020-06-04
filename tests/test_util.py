import pytest
import time
import curio
from diot import Diot
from cmdy import (_cmdy_parse_args, _CmdySyncStreamFromAsync,
                  _cmdy_compose_cmd)

@pytest.mark.parametrize(
    'args,kwargs,ret_args,ret_kwargs,ret_cfgargs,ret_popenargs', [
        (("a", "--l=a", {"x": True}), #args
         {"cmdy_okcode": 1, "cmdy_encoding": "utf-8", "y": False}, #kwargs
         ["a", "--l=a"], # ret_args
         {"x": True}, # ret_kwargs
         {"okcode": [1], "encoding": "utf-8"}, # ret_cfgargs
         {}), # ret_popenargs
        (("a", "--l=a", {"x": True}), #args
         {"cmdy_okcode": 1, "cmdy_encoding": "utf-8",
          "y": False, "popen_close_fds": True}, #kwargs
         ["a", "--l=a"], # ret_args
         {"x": True}, # ret_kwargs
         {"okcode": [1], "encoding": "utf-8"}, # ret_cfgargs
         {"close_fds": True}), # ret_popenargs
        (("a", "--l=a", {"x": True}), #args
         {"cmdy_okcode": 1, "cmdy_encoding": "utf-8", "cmdy_shell": "/bin/sh",
          "y": False, "popen_close_fds": True}, #kwargs
         ["a", "--l=a"], # ret_args
         {"x": True}, # ret_kwargs
         {"okcode": [1], "encoding": "utf-8", "shell": ["/bin/sh", "-c"]}, # ret_cfgargs
         {"close_fds": True}), # ret_popenargs
        (("a", "--l=a", {"x": True}), #args
         {"cmdy_okcode": 1, "cmdy_encoding": "utf-8", "cmdy_shell": ["/bin/sh"],
          "y": False, "popen_close_fds": True}, #kwargs
         ["a", "--l=a"], # ret_args
         {"x": True}, # ret_kwargs
         {"okcode": [1], "encoding": "utf-8", "shell": ["/bin/sh", "-c"]}, # ret_cfgargs
         {"close_fds": True}), # ret_popenargs
    ]
)
def test_parse_args(args, kwargs, ret_args, ret_kwargs,
                    ret_cfgargs, ret_popenargs):

    x_args, x_kwargs, x_cfgargs, x_popenargs = _cmdy_parse_args('', args, kwargs)
    assert x_args == ret_args
    assert x_kwargs == ret_kwargs
    for key, val in ret_cfgargs.items():
        assert x_cfgargs[key] == val
    assert x_popenargs == ret_popenargs
    assert isinstance(x_popenargs, Diot)
    assert isinstance(x_cfgargs, Diot)

def test_parse_args_warnings():

    with pytest.warns(UserWarning):
        args, kwargs, _, _ = _cmdy_parse_args('', args=[{"x":1}],
                                                  kwargs={'x': 2})
    assert args == []
    assert kwargs == {'x': 2}

    with pytest.warns(UserWarning):
        _cmdy_parse_args('', args=[], kwargs={'popen_stdin': 2})
    with pytest.warns(UserWarning):
        _cmdy_parse_args('', args=[], kwargs={'popen_encoding': None})
    with pytest.warns(UserWarning):
        _cmdy_parse_args('', args=[], kwargs={'popen_shell': True})

def test_asnyc_to_sync():

    p = curio.subprocess.Popen(['echo', '-e', '1\\n2\\n3'],
                               stdout=curio.subprocess.PIPE)
    stream = _CmdySyncStreamFromAsync(p.stdout)
    assert stream.dump() == b'1\n2\n3\n'

    p = curio.subprocess.Popen(['echo', '-e', '1\\n2\\n3'],
                               stdout=curio.subprocess.PIPE)
    stream = _CmdySyncStreamFromAsync(p.stdout, encoding='utf-8')
    assert stream.dump() == '1\n2\n3\n'

    p = curio.subprocess.Popen(['echo', '-e', '1\\n2\\n3'],
                               stdout=curio.subprocess.PIPE)

    stream = _CmdySyncStreamFromAsync(p.stdout)
    assert next(stream) == b'1\n'
    assert next(stream) == b'2\n'
    assert next(stream) == b'3\n'

    with pytest.raises(StopIteration):
        next(stream)

    p = curio.subprocess.Popen(['echo', '-e', '1\\n2\\n3'],
                               stdout=curio.subprocess.PIPE)

    stream = _CmdySyncStreamFromAsync(p.stdout, encoding='utf-8')
    assert next(stream) == '1\n'
    assert next(stream) == '2\n'
    assert next(stream) == '3\n'

    with pytest.raises(StopIteration):
        next(stream)

    # test blocking
    p = curio.subprocess.Popen(['bash', '-c',
                                'echo -e "1\\n2\\n3"; sleep .2; echo 4'],
                               stdout=curio.subprocess.PIPE)

    tic = time.time()
    stream = iter(_CmdySyncStreamFromAsync(p.stdout, encoding='utf-8'))

    assert next(stream) == '1\n'
    assert next(stream) == '2\n'
    assert next(stream) == '3\n'
    assert time.time() - tic < .3
    assert next(stream) == '4\n'
    assert time.time() - tic > .2

@pytest.mark.parametrize('args,kwargs,shell,prefix,sep,dupkey,expected', [
    (['ls'], {}, ['bash', '-c'], 'auto', 'auto', False, ['bash', '-c', 'ls']),
    (['ls'], {}, False, 'auto', 'auto', False, ['ls']),
    (['bedtools', 'intersect', '-a', 'file'], {'bfile': 'file2'}, False,
     'auto', 'auto', False,
     ['bedtools', 'intersect', '-a', 'file', '--bfile=file2']),
    (['abc', 'def'], {'': 'file2', 'k': [1,2], 'xyz': [3,4], '_': 'end'},
     False, 'auto', 'auto', False,
     ['abc', 'def', 'file2', '-k', '1', '2', '--xyz=3', '4', 'end']),
    (['abc', 'def'], {'': 'file2', 'k': [1,2], 'xyz': [3,4], '_': 'end'},
     False, 'auto', 'auto', True,
     ['abc', 'def', 'file2', '-k', '1', '-k', '2',
      '--xyz=3', '--xyz=4', 'end']),
])
def test_compose_cmd(args, kwargs, shell, prefix, sep, dupkey, expected):
    assert _cmdy_compose_cmd(args, kwargs,
                             shell=shell, prefix=prefix, sep=sep,
                             dupkey=dupkey) == expected
