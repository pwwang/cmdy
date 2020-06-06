# cmdy
"Shell language" to run command in python

[![pypi][1]][2] [![tag][3]][4] [![travis][5]][6] [![codacy quality][7]][8] [![codacy quality][9]][8] ![pyver][10]

## Installation
```shell
pip install cmdy
```

## Usage

See [Demo](./demo.ipynb)

### Basic usage
```python
from cmdy import ls
print(ls())
```

```python
for line in ls().iter():
    print('Got:', line, end='')
```

#### With non-keyword arguments
```python
from cmdy import tar
print(tar("cvf", "/tmp/test.tar", "./cmdy"))
```

#### With keyword arguments
```python
from cmdy import curl
curl("http://duckduckgo.com/", o="/tmp/page.html", silent=True)
# curl http://duckduckgo.com/ -o /tmp/page.html --silent
```

#### Order keyword arguments
```python
curl("http://duckduckgo.com/", "-o", "/tmp/page.html", "--silent")
# or

from diot import OrderedDiot
kwargs = OrderedDiot()
kwargs.silent = True
kwargs.o = '/tmp/page.html'
curl("http://duckduckgo.com/", kwargs)
# You can also use collections.OrderedDict
```

#### Prefix and separator for keyword arguments
```python
from cmdy import bedtools, bcftools
bedtools.intersect(wa=True, wb=True,
                   a='query.bed', b=['d1.bed', 'd2.bed', 'd3.bed'],
                   names=['d1', 'd2', 'd3'], sorted=True,
                   _prefix='-').h().strcmd
# 'bedtools intersect -wa -wb -a query.bed \
# -b d1.bed d2.bed d3.bed -names d1 d2 d3 -sorted'
```

```python
# default prefix is auto
bcftools.query(_=['a.vcf', 'b.vcf'], H=True,
               format='%CHROM\t%POS\t%REF\t%ALT\n').h().strcmd

# "bcftools query -H --format '%CHROM\t%POS\t%REF\t%ALT\n' a.vcf b.vcf"

ls(l=True, block_size='KB', _sep='auto').h().cmd
['ls', '-l', '--block-size=KB']
```

#### Mixed combinations of prefices and separators in one command
```python
from cmdy import java
# Note this is just an example for old verion picard.
# Picard is changing it's style

picard = java(jar='picard.jar', _prefix='', _sep='=', _sub=True)
c = picard.SortSam(I='input.bam', O='sorted.bam',
               SORTED_ORDER='coordinate',
               _prefix='', _sep='=', _deform=None).h
print(c.cmd)

# same as the above
java({'jar': 'picard.jar', '_prefix': '-', '_sep': ' '},
     'SortSam', I='input.bam', O='sorted.bam',
     SORTED_ORDER='coordinate', _prefix='', _sep='=', _deform=None).h().cmd

# _deform prevents SORTED_ORDER to be deformed to SORTED-ORDER

# ['java', 'jar=picard.jar',
#  'SortSam', 'I=input.bam', 'O=sorted.bam', 'SORTED_ORDER=coordinate']
```

#### Subcommands

```python
from cmdy import git
git.branch(v=True).fg
# <CmdyResult: ['git', 'branch', '-v']>
```

```python
# What if I have separate arguments for main and sub-command?
git(git_dir='.', _sub=True).branch(v=True).h
# <CmdyHolding: ['git', '--git-dir', '.', 'branch', '-v']>
```

#### Duplicated keys for list arguments:
```python
from cmdy import sort
print(sort(k=['1,1', '2,2'], t='_', _='./.editorconfig', _dupkey=True))
# sort -k 1,1 -k 2,2 ./.editorconfig
```

### Return code and exception
```python
from cmdy import x
x()
```

```python console
Traceback (most recent call last):
  File "<ipython-input-16-092cc5b72e61>", line 2, in <module>
    x()
/path/.../to/cmdy/__init__.py", line 146, in __call__
    ready_cfgargs, ready_popenargs, _will())
/path/.../to/cmdy/__init__.py", line 201, in __new__
    result = holding.run()
/path/.../to/cmdy/__init__.py", line 854, in run
    return orig_run(self, wait)
/path/.../to/cmdy/__init__.py", line 717, in run
    return orig_run(self, wait)
/path/.../to/cmdy/__init__.py", line 327, in run
    ret = CmdyResult(self._run(), self)
/path/.../to/cmdy/__init__.py", line 271, in _run
    raise CmdyExecNotFoundError(str(fnfe)) from None
cmdy.cmdy_util.CmdyExecNotFoundError: [Errno 2] No such file or directory: 'x': 'x'
```

```python
from cmdy import ls
ls('non-existing-file')
```

```python console

Traceback (most recent call last):
  File "<ipython-input-17-132683fc2227>", line 2, in <module>
    ls('non-existing-file')
/path/.../to/cmdy/__init__.py", line 146, in __call__
    ready_cfgargs, ready_popenargs, _will())
/path/.../to/cmdy/__init__.py", line 204, in __new__
    return result.wait()
/path/.../to/cmdy/__init__.py", line 407, in wait
    raise CmdyReturnCodeError(self)
cmdy.cmdy_util.CmdyReturnCodeError: Unexpected RETURN CODE 2, expecting: [0]

  [   PID] 167164

  [   CMD] ['ls non-existing-file']

  [STDOUT]

  [STDERR] ls: cannot access non-existing-file: No such file or directory
```

#### Don't raise exception but store the return code
```python
from cmdy import ls
result = ls('non-existing-file', _raise=False)
result.rc # 2
```

#### Tolerance on return code
```python
from cmdy import ls
# or _okcode=[0,2]
ls('non-existing-file', _okcode='0,2').rc # 2
```

### Timeouts
```python
from cmdy import sleep
sleep(3, _timeout=1)
```

```python console
Traceback (most recent call last):
  File "<ipython-input-20-47b0ec7af55f>", line 2, in <module>
    sleep(3, _timeout=1)
/path/.../to/cmdy/__init__.py", line 146, in __call__
    ready_cfgargs, ready_popenargs, _will())
/path/.../to/cmdy/__init__.py", line 204, in __new__
    return result.wait()
/path/.../to/cmdy/__init__.py", line 404, in wait
    ) from None
cmdy.cmdy_util.CmdyTimeoutError: Timeout after 1 seconds.
```

### Redirections
```python
from cmdy import cat
cat('./pytest.ini').redirect > '/tmp/pytest.ini'
print(cat('/tmp/pytest.ini'))
```

#### Appending
```python
# r short for redirect
cat('./pytest.ini').r >> '/tmp/pytest.ini'
print(cat('/tmp/pytest.ini')) # content doubled
```

#### Redirecting to a file handler
```python
with open('/tmp/pytest.ini', 'w') as f
    cat('./pytest.ini').r > f

print(cat('/tmp/pytest.ini'))
```

#### STDIN, STDOUT and/or STDERR redirections
```python
from cmdy import STDIN, STDOUT, STDERR, DEVNULL

c = cat().r(STDIN) < '/tmp/pytest.ini'
print(c)
```

```python
# Mixed
c = cat().r(STDIN, STDOUT) ^ '/tmp/pytest.ini' > DEVNULL
# we can't fetch result from a redirected pipe
print(c.stdout)

# Why not '<' for STDIN?
# Because the priority of the operator is not in sequential order.
# We can use < for STDIN, but we need to ensure it runs first
c = (cat().r(STDIN, STDOUT) < '/tmp/pytest.ini') > DEVNULL
print(c.stdout)

# A simple rule for multiple redirections to always use ">" in the last place
```

```python
# Redirect stderr to stdout
from cmdy import bash
c = bash(c="cat 1>&2").r(STDIN, STDERR) ^ '/tmp/pytest.ini' > STDOUT
print(c.stdout)
```

```python
# Redirect the world
c = bash(c="cat 1>&2").r(STDIN, STDOUT, STDERR) ^ '/tmp/pytest.ini' ^ DEVNULL > STDOUT
print(c.stdout) # None
print(c.stderr) # None
```

### Pipings
```python
from cmdy import grep
c = ls().p | grep('README')
print(c)
# README.md
# README.rst
```

```python
# p short for pipe
c = ls().p | grep('README').p | grep('md')
print(c) # README.md
print(c.piped_strcmds) # ['ls', 'grep README', 'grep md']
```

```python
from cmdy import _CMDY_EVENT
# !!! Pipings should be consumed immediately!
# !!! DO NOT do this
ls().p
ls() # <- Will not run as expected
# All commands will be locked as holding until pipings are consumed
_CMDY_EVENT.clear()
print(ls()) # runs

# See Advanced/Holdings if you want to hold a piping command for a while
```

### Running command in foreground
```python
ls().fg
```

```python
from cmdy import tail
tail('/tmp/pytest.ini', f=True, _timeout=3).fg
# This mimics the `tail -f` program
# You will see the content comes out one after another
# and then program hangs for 3s
```

You can also write an `echo-like` program easily. See '[echo.py](./echo.py)'

### Iterating on output
```python
for line in ls().iter():
    print(line, end='')
```

#### Iterating on stderr
```python
for line in bash(c="cat /tmp/pytest.ini 1>&2").iter(STDERR):
    print(line, end='')
```

#### Getting live output
```python
# Like we did for `tail -f` program
# This time, we can do something with each output line

# Let's use a thread to write content to a file
# And we try to get the live contents using cmdy
import time
from threading import Thread
def live_write(file, n):

    with open(file, 'w', buffering=1) as f:
        # Let's write something every half second
        for i in range(n):
            f.write(str(i) + '\n')
            time.sleep(.5)

test_file = '/tmp/tail-f.txt'
Thread(target=live_write, args=(test_file, 10)).start()

from cmdy import tail

tail_iter = tail(f=True, _=test_file).iter()

for line in tail_iter:
    # Do whatever you want with the line
    print('We got:', line, end='')
    if line.strip() == '8':
        break

# make sure thread ends
time.sleep(2)
```

```python
# What about timeout?

# Of course you can use a timer to check inside the loop
# You can also set a timeout for each fetch

# Terminate after 10 queries

Thread(target=live_write, args=(test_file, 10)).start()

from cmdy import tail

tail_iter = tail(f=True, _=test_file).iter()

for i in range(10):
    print('We got:', tail_iter.next(timeout=1), end='')
```

### Advanced
#### Baking the `cmdy` object

Sometimes, you may want to run the same program a couple of times, with the same set of arguments or configurations, and you don't want to type those arguments every time, then you can bake the Cmdy object with that same arguments or configurations.

For example, if you want to run ls as ls -l all the time:

```python
from cmdy import ls
ll = ls.bake(l=True)
print(ll().h.cmd) # ['ls', '-l']
print(ll(a=True).h.cmd) # ['ls', '-l', '-a']
# I don't want the l flag for some commands occasionally
print(ll(l=False).h.cmd) # ['ls']

# Bake a baked command
lla = ll.bake(a=True)
print(lla().h.cmd) # ['ls', '-l', '-a']
```

```python
# I know git is always gonna run with subcommand
git = git.bake(_sub=True)
# don't bother to pass _sub=True every time
print(git(git_dir='.').branch(v=True).h)
# <CmdyHolding: ['git', '--git-dir', '.', 'branch', '-v']>
print(git().status().h)
# <CmdyHolding: ['git', 'status']>
```

```python
# What if I have a subcommand call 'bake'?
from cmdy import git, CmdyActionError

print(git.branch().h.cmd) # ['git', 'branch']
print(type(git.bake())) # <class 'cmdy.Cmdy'>

# run the git with _sub
print(git(_sub=True).bake().h.cmd) # ['git', 'bake']
```

#### Baking the whole module
```python
import cmdy
# run version of the whole world
sh = cmdy(version=True)
# anything under sh directly will be supposed to have subcommand
from sh import git, gcc
print(git().h)
# <CmdyHolding: ['git', '--version']>
print(gcc().h)
# <CmdyHolding: ['gcc', '--version']>
```

Note that module baking is deep copying, except the exception classes and some utils. This means, you would expect following behavior:

```python
import cmdy
from cmdy import CmdyHolding, CmdyExecNotFoundError

sh = cmdy()

c = sh.echo().h
print(type(c)) # <class 'cmdy.CmdyHolding'>
print(isinstance(c, CmdyHolding)) # False
print(isinstance(c, sh.CmdyHolding)) # True

try:
    sh.notexisting()
except CmdyExecNotFoundError:
    # we can catch it, as CmdyExecNotFoundError is sh.CmdyExecNotFoundError
    print('Catched!')
```

#### Holding objects

You may have noticed that we have a couple of examples above with a final call .h or .h(), which is holding the command from running.

You can do that, too, if you have multiple operations

```python
print(ls().h) # <CmdyHolding: ['ls']>

# however, you cannot hold after some actions
ls().r.h
# CmdyActionError: Should be called in the first place: .h() or .hold()
```

Once a command is on hold (by .h, .hold, .h() or .hold())

You have to explictly call run() to set the command running

```python
from time import time
tic = time()
c = sleep(2).h
print(f'Time elapsed: {time() - tic:.3f} s')
# Time elapsed: 0.022 s

# not running even with fg
c.fg
print(f'Time elapsed: {time() - tic:.3f} s')
# Time elapsed: 0.034 s
c.run()
print(f'Time elapsed: {time() - tic:.3f} s')
# Time elapsed: 2.043 s
```

#### Reuse of command
```python
# After you set a command running,
# you can retrieve the holding object,
# and reuse it
from cmdy import ls
c = ls().fg
# nothing will be produced
c.holding.reset().r > DEVNULL
```

#### Async mode
```python
import curio
from cmdy import ls
a = ls().a # async command is never blocking!

async def main():
    async for line in a:
        print(line, end='')

curio.run(main())
```

#### Extending `cmdy`

All those actions for holding/result objects were implemented internally as plugins. You can right your own plugins, too.

A plugin has to be defined as a class and then instantiated.

**There are 6 APIs for developing a plugin for `cmdy`**

- `cmdy_plugin`: A decorator for the plugin class
- `cmdy_plugin_hold_then`: A decorator to decorate methods in the plugin class, which define actions after a holding object. Arguments:
  - `alias`: The alias of this action (e.g. `r/redir` for `redirect`)
  - `final`: Whether this is a final action, meaning no other actions should be followed
  - `prop`: Whether this action can be called as a property
  - `hold_right`: Should I put right following action on hold? This is useful when we have connectors which then can set the command running. (e.g `>` for redirect and `|` for pipe)
- `cmdy_plugin_run_then`: A decorator to decorate methods in the plugin class, which define actions after a sync result object. Arguments are similar as `cmdy_plugin_hold_then` except that `prop` and `hold_right` are not avaialbe.
- `cmdy_plugin_async_run_then`: Async verion of `cmdy_plugin_run_then`
- `cmdy_plugin_add_method`: A decorator to decorate methods in the plugin class, which add methods to the `CmdyHolding`, `CmdyResult` or `CmdyAsyncResult` class. `cls` is the only argument that specifies which class we are hacking.
- `cmdy_plugin_add_property`: Property version of `cmdy_plugin_add_method`

**Notes on name conflicts:**

If we need to add the methods to multiple classes in the plugin with the same name, you can define a different name with extra underscore suffix(es).

**Notes on module baking:**

- As we mentioned before, `cmdy` module baking are deep copying. So when we can pass the class name instead of the class itself (which you may be not sure which one to use, the orginal one or the one from the baking module) to the `add_method` and `add_property` hooks.
- Plugin enable and disable only take effect within the same module. For example:

    ```python
    import cmdy
    from cmdy import CMDY_PLUGIN_FG
    sh = cmdy()
    # only affects cmdy not sh
    CMDY_PLUGIN_FG.disable()
    # to disable this plugin for sh as well:
    sh.CMDY_PLUGIN_FG.disable()
    ```

```python
# An example to define a plugin
from cmdy import (cmdy_plugin,
                  cmdy_plugin_hold_then,
                  cmdy_plugin_add_method,
                  ls,
                  CmdyActionError)

@cmdy_plugin
class MyPlugin:
    @cmdy_plugin_add_method("CmdyHolding")
    def say_hello(self):
        return 'Hello world!'

    @cmdy_plugin_hold_then('hello')
    def helloworld(self):
        print(self.say_hello())
        # keep chaining
        return self

myplugin = MyPlugin()

# command will never run,
# because we didn't do self.run() in helloworld(self)
ls().helloworld() # prints Hello world!
# property calls enabled by default
ls().helloworld # prints Hello world!
# we have alias
ls().hello # prints Hello world!
```


[1]: https://img.shields.io/pypi/v/cmdy?style=flat-square
[2]: https://pypi.org/project/cmdy/
[3]: https://img.shields.io/github/tag/pwwang/cmdy?style=flat-square
[4]: https://github.com/pwwang/cmdy
[5]: https://img.shields.io/travis/pwwang/cmdy?style=flat-square
[6]: https://travis-ci.org/pwwang/cmdy
[7]: https://img.shields.io/codacy/grade/c82a7081cfc94f089199dafed484e5c3?style=flat-square
[8]: https://app.codacy.com/project/pwwang/cmdy/dashboard
[9]: https://img.shields.io/codacy/coverage/c82a7081cfc94f089199dafed484e5c3?style=flat-square
[10]: https://img.shields.io/pypi/pyversions/cmdy?style=flat-square
