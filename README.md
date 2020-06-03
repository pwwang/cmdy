# cmdy
"Shell language" to command in python

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

### With arguments
```python
from cmdy import tar
tar("cvf", "/tmp/test.tar", "./")
```

[1]: https://img.shields.io/pypi/v/pyppl-report?style=flat-square
[2]: https://pypi.org/project/pyppl-report/
[3]: https://img.shields.io/github/tag/pwwang/pyppl-report?style=flat-square
[4]: https://github.com/pwwang/cmdy
[5]: https://img.shields.io/travis/pwwang/cmdy?style=flat-square
[6]: https://travis-ci.org/pwwang/cmdy
[7]: https://img.shields.io/codacy/grade/c82a7081cfc94f089199dafed484e5c3?style=flat-square
[8]: https://app.codacy.com/project/pwwang/cmdy/dashboard
[9]: https://img.shields.io/codacy/coverage/c82a7081cfc94f089199dafed484e5c3?style=flat-square
[10]: https://img.shields.io/pypi/pyversions/cmdy?style=flat-square
