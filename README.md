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
  ```python
  from sh import ls
  ls = ls.bake(l = True)
  print(ls()) # ls -l
  # but now I somehow want to run `ls` (without `-l`) command with `ls()`
  ls(l = False) # not work
  ```
- Unable to save configurations for commands, since commands have their solid preferences. 
- Unable to specify full path of an executable.
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
__Order keyword arguments:__  
```python
curl("http://duckduckgo.com/", "-o", "page.html", "--silent")
# or 
from collections import OrderedDict
curl("http://duckduckgo.com/", OrderedDict([('o', 'page.html'), ('silent', True)]))
```

__Prefix and separator for keyword arguments:__  
```python
from cmdy import bedtools, bcftools, ls
bedtools.intersect(wa = True, wb = True, a = 'query.bed', b = ['d1.bed', 'd2.bed', 'd3.bed'], names = ['d1', 'd2', 'd3'], sorted = True, _prefix = '-')
#bedtools intersect -wa -wb -a query.bed -b d1.bed d2.bed d3.bed -names d1 d2 d3 -sorted

bcftools.query(_ = ['a.vcf', 'b.vcf'], H = True, format = '%CHROM\t%POS\t%REF\t%ALT\n')
# bcftools query --format '%CHROM\t%POS\t%REF\t%ALT\n' -H a.vcf b.vcf
# _prefix defaults to 'auto' ('-' for short options, '--' for long)
# You may also define arbitrary prefix:
# command(a = 1, bc = 2, _prefix = '---')
# command ---a 1 ---bc 2

ls(l = True, block_size = 'KB', _sep = 'auto')
# ls -l --block-size=KB
# _sep defaults to ' '. 'auto' means ' ' for short options, '=' for long
```

__Different combinations of prefices and separators in one command:__
```python
from cmdy import java
# Note this is just an example for old verion picard. Picard is changing it's style
java({'jar': 'picard.jar', '_prefix': '-', '_sep': ' '}, 'SortSam', I = 'input.bam', O = 'sorted.bam', SORTED_ORDER = 'coordinate', _raw = True, _prefix = '', _sep = '=')
# java -jar picard.jar SortSam I=input.bam O=sorted.bam SORT_ORDER=coordinate
# The first dictionary usees _prefix and _sep in itself if specified, otherwise uses the ones specified with kwargs.
# _raw = True keeps SORTED_ORDER as it is, otherwise, it'll be transformed into SORTED-ORDER
# This is useful when some command has option like '--block-size', but you can still use 'block_size' as keyword argument.
```

__Duplicated keys for list arguments:__
```python
from cmdy import sort
sort(k = ['1,1', '2,2n'], _ = 'a.bed', _dupkey = True)
# sort -k 1,1 -k 2,2n a.bed
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
# or 
# ifconfig(_out = "/tmp/interfaces")

## append
ifconfig(_out = ">") >> "/tmp/interfaces"
# or
# ifconfig(_out_ = "/tmp/interfaces")

# redirect stderr
ifconfig(_err = ">") > "/tmp/ifconfig.errors"
# or ifconfig(_err = "/tmp/ifconfig.errors")
```

## Iteration on output
```python 
from cmdy import tail
for line in tail(_ = 'test.txt', _iter = True):
  print(line)
```

## Background processes
For command you want to run it in non-block mode, you probably would like to use `_bg` keyword:  
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
```python
from cmdy import java
picard = java.bake(dict(jar = 'picard.jar', _sep = ' ', _prefix = '-'))
#picard.SortSam(...)
```

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
```python
# get the permission column
ls(l = True, _pipe = True) | cut(f = 1, _fg = True)
```

## Sub-commands
```python
from cmdy import git
print(git.branch(v = True))
```

## Aliasing/Specifying full path of executables for commands
```python
from cmdy import fc_cache, python
fc_cache(_exe = 'fc-cache', vf = '~/.fonts/', _prefix = '-')
# fc-cache -vf ~/.fonts/

python(_exe = '/home/user/miniconda3/bin/python3', version = True)
# /home/user/miniconda3/bin/python3 --version
```
Always alias `fc_cache` to `fc-cache` and point `python` to `/home/user/miniconda3/bin/python3`, add the following to your `~/.cmdy.ini`  
```ini
[fc_cache]
_exe = fc-cache

[python]
_exe = /home/user/miniconda3/bin/python3
```

Then you don't need to care about the paths any more:
```python
from cmdy import fc_cache, python
fc_cache(vf = '~/.fonts/', _prefix = '-')
# fc-cache -vf ~/.fonts/

python(version = True)
# /home/user/miniconda3/bin/python3 --version
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
  '_raw'     : False,
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

For example, I want to always use raw keyword option:
`~/.cmdy.ini`  
```ini
[default]
_raw: True
```

`ontotator.py`:  
```python
from cmdy import oncotator
oncotator(log_name = '/path/to/log', ...)
# oncotator --log_name LOG_NAME ...
# you don't have to specify _raw = True any more.
```

__Override the settings with environment variable:__
```bash
export CMDY_oncotator__raw=False
python oncotator.py
# will run:
# oncotator --log-name LOG_NAME ...
#                ^
```

