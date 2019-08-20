from __future__ import print_function
import io
import sys
import pytest
from os import path
import cmdy
import time
from tempfile import gettempdir
from collections import OrderedDict
from modkit import NameBannedFromImport

TMPDIR  = gettempdir()
__DIR__ = path.dirname(path.abspath(__file__))

def setup_module():
	cmdy.config.clear()
	cmdy.config._load(dict(default = cmdy._Utils.default_config))

class TestCmdy(object):

	def testBake(self):
		cmdy2 = cmdy(_okcode = [0, 1])
		cmdy2.exit(1)
		with pytest.raises(cmdy2.CmdyReturnCodeException):
			cmdy2.exit(2)

	def testEnv(self):
		from os import environ
		environ['VAR1'] = 'var1'
		assert cmdy.bash(c = 'echo $VAR2', _env = {'VAR2': 'var2'}).strip() == 'var2'
		assert cmdy.bash(c = 'echo $VAR1', _env = {'VAR2': 'var2'}).strip() == 'var1'
		assert cmdy.bash(c = 'echo $VAR1', _env = {'VAR2': 'var2', '_update': False}).strip() == ''

		# reset
		cmd = cmdy.bash(c = 'export VAR1="1$VAR1"; echo $VAR1')
		assert cmd.strip() == '1var1'
		environ['VAR1'] = 'var2'
		cmd.run()
		assert cmd.strip() == '1var1'
		environ['VAR1'] = 'var2'
		cmd.reset()
		cmd.run()
		assert cmd.strip() == '1var2'

	def testReport(self, capfd):
		cmdy.bash(c = 'echo 1', _report = True, _fg = True)
		assert "[cmdy] bash -c 'echo 1'" in capfd.readouterr().err

	def testModule(self):
		from cmdy import ls
		assert isinstance(ls, cmdy.Cmdy)
		with pytest.raises(NameBannedFromImport):
			cmdy.os

	def testCall(self):
		ls_baked  = cmdy.Cmdy('ls')(_bake = True)
		assert isinstance(ls_baked, cmdy.Cmdy)
		cr = ls_baked()
		assert isinstance(cr, cmdy.CmdyResult)
		cr = cmdy.Cmdy('ls').bake(l = True, _exe = 'list')
		assert isinstance(cr, cmdy.Cmdy)
		c = cr(_pipe = True)
		assert c.cmd == 'list -l'
		# release pipe
		with pytest.raises(cmdy.CmdyReturnCodeException):
			c | cmdy.ls()

	def testGetattr(self):
		git = cmdy.Cmdy('git')
		gitshow = git.show
		assert isinstance(gitshow, cmdy.Cmdy)
		assert gitshow._cmd == 'show'


	def testOKCodeBeingOverriden(self):
		ls = cmdy.ls.bake(_okcode = '0~3')
		x = ls()
		assert x.call_args['_okcode'] == [0,1,2,3]

	def testRaise(self):
		bash = cmdy.bash
		with pytest.raises(cmdy.CmdyReturnCodeException):
			bash(c = 'for i in $(seq 1 40); do echo $i; done; exit 1')
		c = bash(c = 'exit 1', _raise = False)
		assert c.rc == 1

		with pytest.raises(cmdy.CmdyReturnCodeException):
			bash(c = 'for i in $(seq 1 40); do echo $i; done 1>&2; exit 1')

		with pytest.raises(cmdy.CmdyReturnCodeException):
			bash(c = 'exit 1', _iter = True).wait()
		with pytest.raises(cmdy.CmdyReturnCodeException):
			bash(c = 'exit 1', _iter = 'err').wait()

	def testDotArgs(self):
		# ** is required
		assert cmdy.bash(**{'.env': {'ABC': '1'}}, c = 'echo $ABC').strip() == '1'

	def testCallArgValidators(self):
		with pytest.raises(ValueError):
			cmdy.bash(c = 'echo 1', _fg = True, _bg = True)

	def testArgsFalse(self):
		assert cmdy.bash(c = 'echo 1', e = False, _hold = 'true').cmd == 'bash -c \'echo 1\''

class TestCmdyResult(object):

	def test(self):
		lsresult = cmdy.ls(__DIR__)
		assert isinstance(lsresult, cmdy.CmdyResult)
		assert path.basename(__file__) in lsresult

	def testReprBool(self):
		assert repr(cmdy.echo(123)) == '123\n'
		assert bool(cmdy.exit(0)) is True
		assert bool(cmdy.exit(1, _raise = False)) is False

	def testPipedCmd(self):
		c = cmdy.echo('1,2,3', _pipe = True) | cmdy.cut(d=',', f=2)
		assert c.strip() == '2'
		assert c.pipedcmd == 'echo 1,2,3 | cut -d , -f 2'
		assert cmdy.echo(123, _hold = True).pipedcmd == 'echo 123'

	def testOKCode(self):
		with pytest.raises(cmdy.CmdyReturnCodeException):
			cmdy.__command_not_exist__()

		ret = cmdy.__command_not_exist__(_okcode = '0,127')
		assert ret == ''

		ret = cmdy.__command_not_exist__(_okcode = 127)
		assert ret == ''

	def testTimeout(self):

		ret = cmdy.bash(c = 'sleep 0.1; echo out', _timeout = 10)
		assert ret.strip() == 'out'

		with pytest.raises(cmdy.CmdyTimeoutException):
			cmdy.bash(c = 'sleep 0.3; echo out', _timeout = .1)

		print('\n======================== Expect to see CmdyTimeoutException ========================')
		list(cmdy.bash(c = 'for i in $(seq 1 8); do echo outiter; sleep 0.1; done', _timeout = .5, _iter = True))

		# timeout at background
		print('\n======================== Expect to see CmdyTimeoutException ========================')
		cmdy.bash(c = 'sleep 0.3; echo out', _bg = True, _timeout = .1)
		time.sleep(.4)

		# expect to see exception
		print('======================== Expect to see CmdyTimeoutException ========================')

	def testFg(self):
		# compose a python file
		pyfile = path.join(TMPDIR, 'testFg.py')

		with open(pyfile, 'w') as f:
			f.write("""from cmdy import bash
bash(c = "echo stdout; echo stderr 1>&2", _fg = True)
""")
		c = cmdy.python(pyfile)
		assert c.stdout.strip() == 'stdout'
		assert c.stderr.strip() == 'stderr'

	def testPipe(self):
		ret = cmdy.bash(c = 'echo -e "1\t2\t3\n4\t5\t6"', _pipe = True) | cmdy.cut(f = 2)
		assert ret.strip() == "2\n5"

		# pipe chain
		ret = (cmdy.bash(c = 'echo -e "1\t2\t3\n4\t5\t6"', _pipe = True) | cmdy.cut(f = 2, _pipe = True)) | cmdy.tail(n = 1)
		assert ret.strip() == "5"

	def testRedirect(self):
		testoutfile = path.join(TMPDIR, 'testRedirectOut.txt')
		cmdy.echo("123", _out = '>') > testoutfile
		with open(testoutfile, 'r') as f:
			assert f.read().strip() == '123'

		cmdy.echo("123", _out = testoutfile)
		with open(testoutfile, 'r') as f:
			assert f.read().strip() == '123'

		cmdy.echo("456", _out = '>') >> testoutfile
		with open(testoutfile, 'r') as f:
			assert f.read().strip() == '123\n456'

		cmdy.echo("456", _out_ = testoutfile)
		with open(testoutfile, 'r') as f:
			assert f.read().strip() == '123\n456\n456'

		testerrfile = path.join(TMPDIR, 'testRedirectErr.txt')
		cmdy.__command_not_exist__(_okcode = 127, _err = testerrfile)
		with open(testerrfile, 'r') as f:
			assert ' not found' in f.read().strip()

		cmdy.__command_not_exist__(_okcode = 127, _err = '>') > testerrfile
		with open(testerrfile, 'r') as f:
			assert ' not found' in f.read().strip()

		cmdy.ls('__file_not_exits__', _okcode = 2, _err = '>') >> testerrfile
		with open(testerrfile, 'r') as f:
			content = f.read()
			assert ' not found' in content
			assert 'No such file or directory' in content

		cmdy.echo('command not found', _out = testerrfile)
		cmdy.ls('__file_not_exits__', _okcode = 2, _err_ = testerrfile)
		with open(testerrfile, 'r') as f:
			content = f.read()
			assert ' not found' in content
			assert 'No such file or directory' in content

	def testResultAsStr(self):
		a = cmdy.echo('123')
		assert str(a).strip() == '123'
		assert a.str().strip() == '123'
		assert a + '456' == '123\n456'
		assert '123' in a
		assert a == '123\n'
		assert a != ''
		assert a.int() == 123
		assert a.float() == 123.0

	def testResultAsInt(self):
		a = cmdy.echo('123')
		assert a.int() == 123
		with pytest.raises(ValueError):
			cmdy.echo('x').int()
		assert cmdy.echo('x').int(raise_exc = False) is None

	def testResultAsFloat(self):
		a = cmdy.echo('123.1')
		assert a.float() == 123.1
		with pytest.raises(ValueError):
			cmdy.echo('x').float()
		assert cmdy.echo('x').float(raise_exc = False) is None

	def testResultAdd(self):
		a = cmdy.echo('123.1')
		assert a + '1' == '123.1\n1'
		with pytest.raises(TypeError):
			cmdy.echo('1234') + 1
		with pytest.raises(TypeError):
			1 in cmdy.echo('1234')

	def testNoSuchAttribute(self):
		with pytest.raises(AttributeError):
			cmdy.echo('x').noattr

	def testCallableBg(self):
		def bg(cmd):
			assert cmd.stdout.strip() == '1'
		cmdy.bash(c = 'echo 1; sleep .5', _bg = bg)
		time.sleep(1)

	def testNoP(self):
		c = cmdy.sleep(.5, _hold = True)
		c.should_wait = False
		c.run()
		c.p = None
		with pytest.raises(cmdy.CmdyReturnCodeException):
			c._wait()

	def testNextExceptions(self):
		with pytest.raises(RuntimeError):
			next(cmdy.bash(c = 'echo 1', _hold = True))
		c = cmdy.bash(c = 'echo 1', _hold = True)
		c.done = True
		with pytest.raises(RuntimeError):
			next(c)
		with pytest.raises(RuntimeError):
			next(cmdy.bash(c = 'echo 1', _stderr = 0, _iter = 'err'))
		with pytest.raises(RuntimeError):
			next(cmdy.bash(c = 'echo 1', _stdout = 0, _iter = 'out'))
		with pytest.raises(RuntimeError):
			next(cmdy.bash(c = 'echo 1', _iter = False))

		c = cmdy.bash(c = 'for i in $(seq 1 7); do echo $i; done', _iter = True)
		for line in c:
			print(line, end = '')
		c.done = False
		# same
		c = cmdy.bash(c = 'for i in $(seq 1 7); do echo $i; done', _iter = True).stdout
		for line in c:
			print(line, end = '')
		# stderr
		c = cmdy.bash(c = 'for i in $(seq 1 7); do echo $i; done 1>&2', _iter = 'err').stderr
		for line in c:
			print(line, end = '')

	
	def testStdoutExc(self):
		c = cmdy.bash(c = 'echo 1', _hold = True)
		with pytest.raises(RuntimeError): # Command not started to run yet.
			c.stdout
		assert cmdy.bash(c = 'echo 1', _fg = True).stdout == ''
		c = cmdy.bash(c = 'echo 1', _hold = True)
		c.run()
		c.p = None
		# Failed to open a process.
		with pytest.raises(RuntimeError):
			c.stdout

		# Background command has not finished yet.
		with pytest.raises(RuntimeError):
			cmdy.sleep(.5, _bg = True).stdout
		
		# stdout REDIRECTED
		c = cmdy.echo(123)
		c.p.stdout = None
		with pytest.raises(RuntimeError):
			c.stdout

	
	def testStderrExc(self):
		c = cmdy.bash(c = 'echo 1', _hold = True)
		with pytest.raises(RuntimeError): # Command not started to run yet.
			c.stderr
		with pytest.raises(RuntimeError):
			cmdy.bash(c = 'echo 1', _fg = True).stderr
		c = cmdy.bash(c = 'echo 1', _hold = True)
		c.run()
		c.p = None
		# Failed to open a process.
		with pytest.raises(RuntimeError):
			c.stderr

		# Background command has not finished yet.
		with pytest.raises(RuntimeError):
			cmdy.sleep(.5, _bg = True).stderr
		
		# stdout REDIRECTED
		c = cmdy.echo(123)
		c.p.stderr = None
		with pytest.raises(RuntimeError):
			c.stderr

class TestUtils(object):

	def testGetPiped(self):
		pp = cmdy._Utils.get_piped()
		assert pp == []
		pp.append(1)
		pp = cmdy._Utils.get_piped()
		assert pp == [1]

	def testParseKwargsEmpty(self):
		kw = cmdy._Utils.parse_kwargs({}, {})
		assert kw == ''

	def testParseKwargsPositional(self):
		kw = cmdy._Utils.parse_kwargs({'_': 1, '': 2}, {})
		assert kw == '2 1'
		kw = cmdy._Utils.parse_kwargs({'_': [1, 2, "a b"], 'a': 6, "": ["3", 4]}, {'_prefix': 'auto', '_sep': ' '})
		assert kw == "3 4 -a 6 1 2 'a b'"

	def testParseKwargsConf(self):
		kw = cmdy._Utils.parse_kwargs({'a':1, 'bc':2, 'def': [3,4,5]}, dict(_prefix = 'auto', _sep = ' ', _dupkey = False))
		assert kw == '-a 1 --bc 2 --def 3 4 5'
		kw = cmdy._Utils.parse_kwargs({'a':1, 'bc':2, 'def': [3,4,5], 'e': True}, dict(_prefix = '---', _sep = '=', _dupkey = True))
		assert kw == '---a=1 ---bc=2 ---def=3 ---def=4 ---def=5 ---e'
		kw = cmdy._Utils.parse_kwargs({'a':1, 'bc':2, 'def': [3,4,5], 'e': True}, dict(_prefix = '-', _sep = 'auto', _dupkey = True))
		assert kw == '-a 1 -bc=2 -def=3 -def=4 -def=5 -e'

		# _raw
		kw = cmdy._Utils.parse_kwargs(dict(a_b = 1), dict(_prefix = 'auto', _sep = ' ', _dupkey = False, _raw = False), True)
		assert kw == '--a-b 1'
		kw = cmdy._Utils.parse_kwargs(dict(a_b = 1), dict(_prefix = 'auto', _sep = ' ', _dupkey = False, _raw = True), True)
		assert kw == '--a_b 1'

	def testParseKwargsOrder(self):
		kw = cmdy._Utils.parse_kwargs(OrderedDict([('a', 1), ('def', [3, 4, 5]), ('bc', 2)]), dict(_prefix = 'auto', _sep = ' ', _dupkey = False))
		assert kw == '-a 1 --def 3 4 5 --bc 2'

	def testParseArgs(self):
		args, keywords, kwargs, call_args, popen_args = cmdy._Utils.parse_args('ls', ['-l'], {'color': True})
		assert args == '-l'
		assert keywords == {'':[], '_':[], 'color': True}
		assert kwargs == {key: cmdy._Utils.default_config[key] for key in cmdy._Utils.kw_arg_keys if key in cmdy._Utils.default_config}
		assert call_args == {key: cmdy._Utils.default_config[key] for key in cmdy._Utils.call_arg_keys if key in cmdy._Utils.default_config}
		assert popen_args == {key: cmdy._Utils.default_config[key] for key in cmdy._Utils.popen_arg_keys if key in cmdy._Utils.default_config}

		args, keywords, kwargs, call_args, popen_args = cmdy._Utils.parse_args('ls', ['-l', {'_' : [1,2], '': 4, 'a': 8, 'bc': 'New File'}], {'color': True, '_prefix': '-'})
		assert args == "-l 4 -a 8 -bc 'New File' 1 2"
		assert keywords == {'':[], '_':[], 'color': True}
		assert kwargs == {'_prefix': '-', '_sep': ' ', '_raw': False, '_dupkey': False}
