import pytest
import time
import curio
from diot import Diot
from cmdy import CMDY_CONFIG, _CMDY_BAKED_ARGS
from cmdy.cmdy_util import (
    _cmdy_parse_args, _CmdySyncStreamFromAsync,
    _cmdy_compose_arg_segment, _cmdy_parse_single_kwarg,
    _cmdy_compose_cmd, _cmdy_fix_popen_config
)

@pytest.mark.parametrize('cmd_args,config,expected', [
    ({'a': 1, 'ab': 2}, {}, ['-a', '1', '--ab', '2']),
    ({'a': 1, 'ab': 2}, {'prefix': '--'}, ['--a', '1', '--ab', '2']),
    ({'a': 1, 'ab': 2, 'cd': [3,4]}, {'sep': '='},
     ['-a=1', '--ab=2', '--cd=3', '4']),
    ({'a': True, 'ab': 2}, {}, ['-a', '--ab', '2']),
    ({'a': False, 'ab': 2}, {}, ['--ab', '2']),
    ({'a': [1, 2]}, {}, ['-a', '1', '2']),
    ({'a': [1, 2]}, {'dupkey': True}, ['-a', '1', '-a', '2']),
    ({'_': [3, 4], '': [1, 2]}, {}, ['1', '2', '3', '4']),
])
def test_cmdy_compose_arg_segment(cmd_args, config, expected):
    conf = CMDY_CONFIG.copy()
    conf.update(config)
    assert _cmdy_compose_arg_segment(cmd_args, conf) == expected

@pytest.mark.parametrize('''kwargs,is_root,global_config,expected_pure,
expected_config,expected_popen''', [
    ({'a': 1, 'boy': 2, 'cmdy_prefix': '--'}, True, {},
     {'a': 1, 'boy': 2}, {'prefix': '--'}, {}),
])
def test_cmdy_parse_single_kwarg(kwargs, is_root, global_config, expected_pure,
                                 expected_config, expected_popen):
    gconfig = CMDY_CONFIG.copy()
    gconfig.update(global_config)
    ret_pure, ret_config, ret_popen = _cmdy_parse_single_kwarg(
        kwargs, is_root, gconfig
    )
    assert expected_pure == ret_pure
    for key, val in expected_config.items():
        assert expected_config[key] == val
    assert expected_popen == ret_popen

def test_fix_popen_config():
    config = Diot({'envs': {'x': 1}, 'env': {'x': 2}})
    with pytest.warns(UserWarning):
        _cmdy_fix_popen_config(config)

    assert 'envs' not in config
    assert config['env']['x'] == '2'

    config = Diot({'envs': {'x': True}})
    _cmdy_fix_popen_config(config)
    assert 'envs' not in config
    assert config['env']['x'] == '1'
    # other envs loaded
    assert len(config['env']) > 1


@pytest.mark.parametrize(
    'args,kwargs,ret_args,ret_cfgargs,ret_popenargs', [
        (("a", "--l=a", {"x": True}), #args
         {"cmdy_okcode": 1, "cmdy_encoding": "utf-8", "y": False}, #kwargs
         ["a", "--l=a", "-x"], # ret_args
         {"okcode": [1], "encoding": "utf-8"}, # ret_cfgargs
         {}), # ret_popenargs
        (("a", "--l=a", {"x": True}), #args
         {"_okcode": 1, "_encoding": "utf-8", "y": False,
          "_cwd": "path", "_notaconf": True}, #kwargs
         ["a", "--l=a", "-x", "--_notaconf"], # ret_args
         {"okcode": [1], "encoding": "utf-8"}, # ret_cfgargs
         {"cwd": "path"}), # ret_popenargs
        (("a", "--l=a", {"x": True}), #args
         {"cmdy_okcode": 1, "cmdy_encoding": "utf-8",
          "y": False, "popen_close_fds": True}, #kwargs
         ["a", "--l=a", "-x"], # ret_args
         {"okcode": [1], "encoding": "utf-8"}, # ret_cfgargs
         {"close_fds": True}), # ret_popenargs
        (("a", "--l=a", {"x": True}), #args
         {"cmdy_okcode": '0,1', "cmdy_encoding": "utf-8", "cmdy_shell": "/bin/sh",
          "y": False, "popen_close_fds": True}, #kwargs
         ["a", "--l=a", "-x"], # ret_args
         {"okcode": [0,1], "encoding": "utf-8", "shell": ["/bin/sh", "-c"]}, # ret_cfgargs
         {"close_fds": True}), # ret_popenargs
        (("a", "--l=a", {"x": False}), #args
         {"cmdy_okcode": 1, "cmdy_encoding": "utf-8", "cmdy_shell": ["/bin/sh"],
          "y": False, "popen_close_fds": True}, #kwargs
         ["a", "--l=a"], # ret_args
         {"okcode": [1], "encoding": "utf-8", "shell": ["/bin/sh", "-c"]}, # ret_cfgargs
         {"close_fds": True}), # ret_popenargs
    ]
)
def test_parse_args(args, kwargs, ret_args,
                    ret_cfgargs, ret_popenargs):

    x_args, x_cfgargs, x_popenargs = _cmdy_parse_args(
        '', args, kwargs, CMDY_CONFIG, _CMDY_BAKED_ARGS
    )
    assert x_args == ret_args
    for key, val in ret_cfgargs.items():
        assert x_cfgargs[key] == val
    assert x_popenargs == ret_popenargs
    assert isinstance(x_popenargs, Diot)
    assert isinstance(x_cfgargs, Diot)

def test_parse_args_warnings():

    with pytest.warns(UserWarning):
        args, _, _ = _cmdy_parse_args('', [{"x":1}],
                                           {'x': 2},
                                           CMDY_CONFIG, _CMDY_BAKED_ARGS)
    assert args == ['-x', '2']

    with pytest.warns(UserWarning):
        _cmdy_parse_args('', [], {'popen_stdin': 2},
                         CMDY_CONFIG, _CMDY_BAKED_ARGS)
    with pytest.warns(UserWarning):
        _cmdy_parse_args('', [], {'popen_encoding': None},
                         CMDY_CONFIG, _CMDY_BAKED_ARGS)
    with pytest.warns(UserWarning):
        _cmdy_parse_args('', [], {'popen_shell': True},
                         CMDY_CONFIG, _CMDY_BAKED_ARGS)

def test_parse_args_exception():
    with pytest.raises(ValueError):
        _cmdy_parse_args('', [{'popen_cwd': ''}], {},
                         CMDY_CONFIG, _CMDY_BAKED_ARGS)

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

@pytest.mark.parametrize('args,shell,expected', [
    (['ls'], ['bash', '-c'], ['bash', '-c', 'ls']),
    (['ls'], False, ['ls']),
    (['bedtools', 'intersect', '-a', 'file'], False,
     ['bedtools', 'intersect', '-a', 'file']),
    (['abc', 'def'],
     False,
     ['abc', 'def']),
])
def test_compose_cmd(args, shell, expected):
    assert _cmdy_compose_cmd(args, shell=shell) == expected
