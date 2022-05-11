import pytest
import time
import curio
from diot import Diot
from simpleconf import ProfileConfig
from cmdy.cmdy_defaults import get_config
from cmdy.cmdy_utils import (
    parse_args,
    SyncStreamFromAsync,
    compose_arg_segment,
    parse_single_kwarg,
    compose_cmd,
    fix_popen_config,
    property_called_as_method,
    property_or_method,
)

CONFIG = get_config()


def test_cmdy_property_called_as_method():
    class C:
        @property
        def c(self):
            ret = property_called_as_method()
            if ret:
                return ret
            return lambda: ret

    c = C()
    assert c.c
    assert not c.c()


def testproperty_or_method():
    class C:
        @property
        @property_or_method
        def c(self, n=1):
            return n

    c = C()
    assert c.c == 1
    x = c.c(2)
    assert x == 2


@pytest.mark.parametrize(
    "cmd_args,config,expected",
    [
        ({"a": 1, "ab": 2}, {}, ["-a", "1", "--ab", "2"]),
        ({"a": 1, "ab": 2}, {"prefix": "--"}, ["--a", "1", "--ab", "2"]),
        (
            {"a": 1, "ab": 2, "cd": [3, 4]},
            {"sep": "="},
            ["-a=1", "--ab=2", "--cd=3", "4"],
        ),
        ({"a": True, "ab": 2}, {}, ["-a", "--ab", "2"]),
        ({"a": False, "ab": 2}, {}, ["--ab", "2"]),
        ({"a": [1, 2]}, {}, ["-a", "1", "2"]),
        ({"a": [1, 2]}, {"dupkey": True}, ["-a", "1", "-a", "2"]),
        ({"a_b": [1, 2]}, {"dupkey": True}, ["--a-b", "1", "--a-b", "2"]),
        (
            {"a_b": [1, 2]},
            {"dupkey": True, "deform": False},
            ["--a_b", "1", "--a_b", "2"],
        ),
        ({"_": [3, 4], "": [1, 2]}, {}, ["1", "2", "3", "4"]),
    ],
)
def testcompose_arg_segment(cmd_args, config, expected):
    conf = CONFIG.copy()
    conf.update(config)
    assert compose_arg_segment(cmd_args, conf) == expected


@pytest.mark.parametrize(
    """kwargs,is_root,global_config,expected_pure,
expected_config,expected_popen""",
    [
        (
            {"a": 1, "boy": 2, "cmdy_prefix": "--"},
            True,
            {},
            {"a": 1, "boy": 2},
            {"prefix": "--"},
            {},
        ),
    ],
)
def testparse_single_kwarg(
    kwargs,
    is_root,
    global_config,
    expected_pure,
    expected_config,
    expected_popen,
):
    gconfig = CONFIG.copy()
    gconfig.update(global_config)
    ret_pure, ret_config, ret_popen = parse_single_kwarg(
        kwargs, is_root, gconfig
    )
    assert expected_pure == ret_pure
    for key, val in expected_config.items():
        assert expected_config[key] == val
    assert expected_popen == ret_popen


def test_fix_popen_config():
    config = Diot({"envs": {"x": 1}, "env": {"x": 2}})
    with pytest.warns(UserWarning):
        fix_popen_config(config)

    assert "envs" not in config
    assert config["env"]["x"] == "2"

    config = Diot({"envs": {"x": True}})
    fix_popen_config(config)
    assert "envs" not in config
    assert config["env"]["x"] == "1"
    # other envs loaded
    assert len(config["env"]) > 1


@pytest.mark.parametrize(
    "args,kwargs,ret_args,ret_kwargs,ret_cfgargs,ret_popenargs",
    [
        (
            ("a", "--l=a", {"x": True}),  # args
            {"cmdy_okcode": 1, "cmdy_encoding": "utf-8", "y": False},  # kwargs
            ["a", "--l=a", "-x"],  # ret_args
            {"y": False},  # ret_kwargs
            {"okcode": [1], "encoding": "utf-8"},  # ret_cfgargs
            {},
        ),  # ret_popenargs
        (
            ("a", "--l=a", {"x": True}),  # args
            {
                "_okcode": 1,
                "_encoding": "utf-8",
                "y": False,
                "_cwd": "path",
                "_notaconf": True,
            },  # kwargs
            ["a", "--l=a", "-x"],  # ret_args
            {"_notaconf": True, "y": False},  # ret_kwargs
            {"okcode": [1], "encoding": "utf-8"},  # ret_cfgargs
            {"cwd": "path"},
        ),  # ret_popenargs
        (
            ("a", "--l=a", {"x": True}),  # args
            {
                "cmdy_okcode": 1,
                "cmdy_encoding": "utf-8",
                "y": False,
                "popen_close_fds": True,
            },  # kwargs
            ["a", "--l=a", "-x"],  # ret_args
            {"y": False},  # ret_kwargs
            {"okcode": [1], "encoding": "utf-8"},  # ret_cfgargs
            {"close_fds": True},
        ),  # ret_popenargs
        (
            ("a", "--l=a", {"x": True}),  # args
            {
                "cmdy_okcode": "0,1",
                "cmdy_encoding": "utf-8",
                "cmdy_shell": "/bin/sh",
                "y": False,
                "popen_close_fds": True,
            },  # kwargs
            ["a", "--l=a", "-x"],  # ret_args
            {"y": False},  # ret_kwargs
            {
                "okcode": [0, 1],
                "encoding": "utf-8",
                "shell": ["/bin/sh", "-c"],
            },  # ret_cfgargs
            {"close_fds": True},
        ),  # ret_popenargs
        (
            ("a", "--l=a", {"x": False}),  # args
            {
                "cmdy_okcode": 1,
                "cmdy_encoding": "utf-8",
                "cmdy_shell": ["/bin/sh"],
                "y": False,
                "popen_close_fds": True,
            },  # kwargs
            ["a", "--l=a"],  # ret_args
            {"y": False},  # ret_kwargs
            {
                "okcode": [1],
                "encoding": "utf-8",
                "shell": ["/bin/sh", "-c"],
            },  # ret_cfgargs
            {"close_fds": True},
        ),  # ret_popenargs
    ],
)
def test_parse_args(
    args, kwargs, ret_args, ret_kwargs, ret_cfgargs, ret_popenargs
):

    x_args = parse_args("", args, kwargs, CONFIG, {})
    assert x_args.args == ret_args
    for key, val in ret_cfgargs.items():
        assert x_args.config[key] == val
    assert x_args.kwargs == ret_kwargs
    assert x_args.popen == ret_popenargs
    assert isinstance(x_args.popen, Diot)
    assert isinstance(x_args.config, Diot)


def test_parse_args_config():
    args = parse_args(
        "ls",
        (),
        {},
        ProfileConfig.load({"default": {}, "ls": {"l": True}}),
        {},
    )
    assert args.config["l"] is True


def test_parse_args_warnings():

    with pytest.warns(UserWarning):
        args = parse_args("", [{"x": 1}], {"x": 2}, CONFIG, {})
    assert args.kwargs == {"x": 2}

    with pytest.warns(UserWarning):
        parse_args("", [], {"popen_stdin": 2}, CONFIG, {})
    with pytest.warns(UserWarning):
        parse_args("", [], {"popen_encoding": None}, CONFIG, {})
    with pytest.warns(UserWarning):
        parse_args("", [], {"popen_shell": True}, CONFIG, {})


def test_parse_args_exception():
    with pytest.raises(ValueError):
        parse_args("", [{"popen_cwd": ""}], {}, CONFIG, {})


def test_asnyc_to_sync():

    p = curio.subprocess.Popen(
        ["echo", "-e", "1\\n2\\n3"], stdout=curio.subprocess.PIPE
    )
    stream = SyncStreamFromAsync(p.stdout)
    assert stream.dump() == b"1\n2\n3\n"

    p = curio.subprocess.Popen(
        ["echo", "-e", "1\\n2\\n3"], stdout=curio.subprocess.PIPE
    )
    stream = SyncStreamFromAsync(p.stdout, encoding="utf-8")
    assert stream.dump() == "1\n2\n3\n"

    p = curio.subprocess.Popen(
        ["echo", "-e", "1\\n2\\n3"], stdout=curio.subprocess.PIPE
    )

    stream = SyncStreamFromAsync(p.stdout)
    assert next(stream) == b"1\n"
    assert next(stream) == b"2\n"
    assert next(stream) == b"3\n"

    with pytest.raises(StopIteration):
        next(stream)

    p = curio.subprocess.Popen(
        ["echo", "-e", "1\\n2\\n3"], stdout=curio.subprocess.PIPE
    )

    stream = SyncStreamFromAsync(p.stdout, encoding="utf-8")
    assert next(stream) == "1\n"
    assert next(stream) == "2\n"
    assert next(stream) == "3\n"

    with pytest.raises(StopIteration):
        next(stream)

    # test blocking
    p = curio.subprocess.Popen(
        ["bash", "-c", 'echo -e "1\\n2\\n3"; sleep .2; echo 4'],
        stdout=curio.subprocess.PIPE,
    )

    tic = time.time()
    stream = iter(SyncStreamFromAsync(p.stdout, encoding="utf-8"))

    assert next(stream) == "1\n"
    assert next(stream) == "2\n"
    assert next(stream) == "3\n"
    assert time.time() - tic < 0.3
    assert next(stream) == "4\n"
    assert time.time() - tic > 0.2


@pytest.mark.parametrize(
    "args,kwargs,config,shell,expected",
    [
        (["ls"], {"l": True}, {}, ["bash", "-c"], ["bash", "-c", "ls -l"]),
        (["ls"], {}, {}, False, ["ls"]),
        (
            ["bedtools", "intersect", "-a", "file"],
            {"bfile": "file"},
            {},
            {},
            ["bedtools", "intersect", "-a", "file", "--bfile", "file"],
        ),
        (["abc", "def"], {"ab": 2}, {}, False, ["abc", "def", "--ab", "2"]),
    ],
)
def test_compose_cmd(args, kwargs, shell, config, expected):
    conf = CONFIG.copy()
    conf.update(config)
    assert compose_cmd(args, kwargs, conf, shell=shell) == expected
