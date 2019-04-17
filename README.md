# cmdy
A handy package to run command from python

## Installation
```shell
# latest version
pip install git+https://github.com/pwwang/cmdy
# released version
pip install cmdy
```

## Why another one beyond `sh`?
- `oncotator` not running with `sh`, no matter what I tried.
- Unable to replace arguments with baked command, see example below:
  ```
  from sh import ls
  ll = ls.bake(l = True)
  print(ll()) # ls -l
  # but now I somehow want to run `ls` (without `-l`) command with `ll`
  ll(l = False) # not work
  ```
- Unable to save configurations for commands, since commands have their solid preferences. 
- No pipe/redirection notations.

## Basic usage
```python
from cmdy import ls
print(ls())
```
### With arguments
Like `sh`, `cmdy` can have non-keyword arguments, but keyword arguments preferred.
```python
from cmdy import tar
tar("cvf", "/tmp/test.tar", "/my/home/directory/")
```

### With keyword arguments
```python
curl("http://duckduckgo.com/", o="page.html", silent=True)
# curl http://duckduckgo.com/ -o page.html --silent
```
Order keyword arguments:  
```python
curl("http://duckduckgo.com/", "-o", "page.html", "--silent")
# or 
from collections import OrderedDict
curl("http://duckduckgo.com/", OrderedDict([('o', 'page.html'), ('silent', True)]))
```

## Return codes and exceptions
```python
from cmdy import x
x()
```

```shell
    ... ...
    raise CmdyReturnCodeException(self)
          │                       └
          └ <class 'cmdy.CmdyReturnCodeException'>
cmdy.CmdyReturnCodeException: Unexpected RETURN CODE 127, expecting: [0]

  [PID]    38254

  [CMD]    x

  [STDERR] /bin/sh: x: command not found

```
You can use try/catch to catch it:  
```python
from cmdy import x, CmdyReturnCodeException
try:
	x()
except CmdyReturnCodeException as ex
	print('Command returned %s' % ex.cmdy.rc)
```

You can allow multiple return codes by: `x(_okcode = [0, 127])` or `x(_okcode = '0,127')`

## Redirection
```python
from cmdy import ifconfig
ifconfig(_out="/tmp/interfaces")
# or you can use shell redirection notation
ifconfig(_out = ">") > "/tmp/interfaces"
## append
ifconfig(_out = ">") >> "/tmp/interfaces"
```

## Iteration on output
```python 
from cmdy import tail
for line in tail(_ = 'test.txt', _iter = True):
	print(line)
```

## Background processes
For command not intended to end, you have to put it in background:  
```python
for line in tail(_ = 'test.txt', _bg = True, _iter = True):
	print(line)
```

```python
# blocks
sleep(3)
print("...3 seconds later")

# doesn't block
p = sleep(3, _bg=True)
print("prints immediately!")
p.wait()
print("...and 3 seconds later")
```

Callbacks for background processes:  
```python
import time
from cmdy import sleep
def callback(cmdy):
	print(cmdy.rc)
p = sleep(3, _bg = callback)
p.wait()
# prints 0
```

## Baking
Unlike `sh`, `cmdy` holds the keyword arguments, and updates them while baked into a new command. This enables it to replace some arguments with the new baked command.  
```python
from cmdy import ls

ls = ls.bake(l = True)
# or ls = ls(l = True, _bake = True)
ls() # ls -l

# I don't want -l anymore
ls(l = False)
```

Note that non-keyword arguments is not updatable.  
```python
ls = ls.bake('-l')
ls() # ls -l

# Not work, still ls -l
ls(l = False)
```

Bake the whole module:  
```python
import cmdy
cmdy = cmdy(_fg = True)
# all commands under new module is running at foreground (stdout = sys.stdout, stderr = stderr)
from cmdy import ls
ls()
```

## Piping
```
ls(l = True, _pipe = True) | cut(f = 5, _fg = True)
```

## Sub-commands
```python
from cmdy import git
print(git.branch(v = True))
```

## Configuration
`cmdy` will first load default arguments:
```python
{
	'_okcode'  : 0,
	'_exe'     : None,
	'_sep'     : ' ',
	'_prefix'  : 'auto',
	'_dupkey'  : False,
	'_bake'    : False,
	'_iter'    : False,
	'_pipe'    : False,
	'_timeout' : 0,
	'_encoding': 'utf-8',
	'_bg'      : False,
	'_fg'      : False,
	'_out'     : None,
	'_out_'    : None,
	'_err'     : None,
	'_err_'    : None
}
```
And then try to load `$HOME/.cmdy.ini`, `./.cmdy.ini` and environment variables starting with `CMDY_`, so you can overwrite the configurations with temporary environment variables.

For example, I want all commands to finish in 3 seconds:
`~/.cmdy.ini`  
```ini
[default]
_timeout: 3
```
```python
from cmdy import sleep
sleep(4) # raise CmdyTimeoutExceptioin

import os
os.environ['CMDY_sleep__timeout'] = 5
sleep(4) # ok
```

## TODO:
- Writing tests
