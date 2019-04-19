from __future__ import print_function

from os import path
import unittest
import cmdy
import time
from tempfile import gettempdir
from collections import OrderedDict
from modkit import NameBannedFromImport

TMPDIR  = gettempdir()
__DIR__ = path.dirname(path.abspath(__file__))

def load_default_config():
	cmdy.config.clear()
	cmdy.config._load(dict(default = cmdy._Utils.default_config))

load_default_config()

class TestCmdy(unittest.TestCase):

	def testModule(self):
		from cmdy import ls
		self.assertIsInstance(ls, cmdy.Cmdy)
		self.assertRaises(NameBannedFromImport, getattr, cmdy, 'os')

	def testCall(self):
		cmd = cmdy.Cmdy('ls')
		cr  = cmdy.Cmdy('ls')(_bake = True)
		self.assertIsInstance(cr, cmdy.Cmdy)
		cr = cmdy.Cmdy('ls')()
		self.assertIsInstance(cr, cmdy.CmdyResult)
		cr = cmdy.Cmdy('ls').bake(l = True)
		self.assertIsInstance(cr, cmdy.Cmdy)
	
	def testGetattr(self):
		git = cmdy.Cmdy('git')
		gitshow = git.show
		self.assertIsInstance(gitshow, cmdy.Cmdy)
		self.assertEqual(gitshow._cmd, 'show')


class TestCmdyResult(unittest.TestCase):
	
	def test(self):
		lsresult = cmdy.ls(__DIR__)
		self.assertIsInstance(lsresult, cmdy.CmdyResult)
		self.assertTrue("test.py" in lsresult)

	def testOKCode(self):

		self.assertRaises(cmdy.CmdyReturnCodeException, cmdy.__command_not_exist__)

		ret = cmdy.__command_not_exist__(_okcode = '0,127')
		self.assertEqual(ret, '')

		ret = cmdy.__command_not_exist__(_okcode = 127)
		self.assertEqual(ret, '')

	def testTimeout(self):

		ret = cmdy.bash(c = 'sleep 0.1; echo out')
		self.assertEqual(ret.strip(), 'out')

		self.assertRaises(cmdy.CmdyTimeoutException, cmdy.bash, c = 'sleep 0.3; echo out', _timeout = 0.1)

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
		self.assertEqual(c.stdout.strip(), 'stdout')
		self.assertEqual(c.stderr.strip(), 'stderr')

	def testPipe(self):
		ret = cmdy.bash(c = 'echo -e "1\t2\t3\n4\t5\t6"', _pipe = True) | cmdy.cut(f = 2)
		self.assertEqual(ret.strip(), "2\n5")
		
		# pipe chain
		ret = (cmdy.bash(c = 'echo -e "1\t2\t3\n4\t5\t6"', _pipe = True) | cmdy.cut(f = 2, _pipe = True)) | cmdy.tail(n = 1)
		self.assertEqual(ret.strip(), "5")

	def testRedirect(self):
		testoutfile = path.join(TMPDIR, 'testRedirectOut.txt')
		cmdy.echo("123", _out = '>') > testoutfile
		with open(testoutfile, 'r') as f:
			self.assertEqual(f.read().strip(), '123')

		cmdy.echo("123", _out = testoutfile)
		with open(testoutfile, 'r') as f:
			self.assertEqual(f.read().strip(), '123')

		cmdy.echo("456", _out = '>') >> testoutfile
		with open(testoutfile, 'r') as f:
			self.assertEqual(f.read().strip(), '123\n456')
		
		cmdy.echo("456", _out_ = testoutfile)
		with open(testoutfile, 'r') as f:
			self.assertEqual(f.read().strip(), '123\n456\n456')

		testerrfile = path.join(TMPDIR, 'testRedirectErr.txt')
		cmdy.__command_not_exist__(_okcode = 127, _err = testerrfile)
		with open(testerrfile, 'r') as f:
			self.assertIn('command not found', f.read().strip())

		cmdy.__command_not_exist__(_okcode = 127, _err = '>') > testerrfile
		with open(testerrfile, 'r') as f:
			self.assertIn('command not found', f.read().strip())

		cmdy.ls('__file_not_exits__', _okcode = 2, _err = '>') >> testerrfile
		with open(testerrfile, 'r') as f:
			content = f.read()
			self.assertIn('command not found', content)
			self.assertIn('No such file or directory', content)

		cmdy.echo('command not found', _out = testerrfile)
		cmdy.ls('__file_not_exits__', _okcode = 2, _err_ = testerrfile)
		with open(testerrfile, 'r') as f:
			content = f.read()
			self.assertIn('command not found', content)
			self.assertIn('No such file or directory', content)
		
	def testResultAsStr(self):
		a = cmdy.echo('123')
		self.assertEqual(a + '456', '123\n456')
		self.assertIn('123', a)
		self.assertTrue(a == '123\n')
		self.assertTrue(a != '')
		self.assertEqual(a.int(), 123)
		self.assertEqual(a.float(), 123.0)
	
class TestUtils(unittest.TestCase):
	
	def testGetPiped(self):
		pp = cmdy._Utils.get_piped()
		self.assertEqual(pp, [])
		pp.append(1)
		pp = cmdy._Utils.get_piped()
		self.assertEqual(pp, [1])
	
	def testParseKwargsEmpty(self):
		kw = cmdy._Utils.parse_kwargs({}, {})
		self.assertEqual(kw, '')
	
	def testParseKwargsPositional(self):
		kw = cmdy._Utils.parse_kwargs({'_': 1, '': 2}, {})
		self.assertEqual(kw, '2 1')
		kw = cmdy._Utils.parse_kwargs({'_': [1, 2, "a b"], 'a': 6, "": ["3", 4]}, {'_prefix': 'auto', '_sep': ' '})
		self.assertEqual(kw, "3 4 -a 6 1 2 'a b'")

	def testParseKwargsConf(self):
		kw = cmdy._Utils.parse_kwargs({'a':1, 'bc':2, 'def': [3,4,5]}, dict(_prefix = 'auto', _sep = ' ', _dupkey = False))
		self.assertEqual(kw, '-a 1 --bc 2 --def 3 4 5')
		kw = cmdy._Utils.parse_kwargs({'a':1, 'bc':2, 'def': [3,4,5], 'e': True}, dict(_prefix = '---', _sep = '=', _dupkey = True))
		self.assertEqual(kw, '---a=1 ---bc=2 ---def=3 ---def=4 ---def=5 ---e')
		kw = cmdy._Utils.parse_kwargs({'a':1, 'bc':2, 'def': [3,4,5], 'e': True}, dict(_prefix = '-', _sep = 'auto', _dupkey = True))
		self.assertEqual(kw, '-a 1 -bc=2 -def=3 -def=4 -def=5 -e')

		# _raw
		kw = cmdy._Utils.parse_kwargs(dict(a_b = 1), dict(_prefix = 'auto', _sep = ' ', _dupkey = False, _raw = False), True)
		self.assertEqual(kw, '--a-b 1')
		kw = cmdy._Utils.parse_kwargs(dict(a_b = 1), dict(_prefix = 'auto', _sep = ' ', _dupkey = False, _raw = True), True)
		self.assertEqual(kw, '--a_b 1')

	def testParseKwargsOrder(self):
		kw = cmdy._Utils.parse_kwargs(OrderedDict([('a', 1), ('def', [3, 4, 5]), ('bc', 2)]), dict(_prefix = 'auto', _sep = ' ', _dupkey = False))
		self.assertEqual(kw, '-a 1 --def 3 4 5 --bc 2')

	def testParseArgs(self):
		args, keywords, kwargs, call_args, popen_args = cmdy._Utils.parse_args('ls', ['-l'], {'color': True})
		self.assertEqual(args, '-l')
		self.assertEqual(keywords, {'':[], '_':[], 'color': True})
		self.assertEqual(kwargs, {key: cmdy._Utils.default_config[key] for key in cmdy._Utils.kw_arg_keys if key in cmdy._Utils.default_config})
		self.assertEqual(call_args, {key: cmdy._Utils.default_config[key] for key in cmdy._Utils.call_arg_keys if key in cmdy._Utils.default_config})
		self.assertEqual(popen_args, {key: cmdy._Utils.default_config[key] for key in cmdy._Utils.popen_arg_keys if key in cmdy._Utils.default_config})

		args, keywords, kwargs, call_args, popen_args = cmdy._Utils.parse_args('ls', ['-l', {'_' : [1,2], '': 4, 'a': 8, 'bc': 'New File'}], {'color': True, '_prefix': '-'})
		self.assertEqual(args, "-l 4 -a 8 -bc 'New File' 1 2")
		self.assertEqual(keywords, {'':[], '_':[], 'color': True})
		self.assertEqual(kwargs, {'_prefix': '-', '_sep': ' ', '_raw': False, '_dupkey': False})


if __name__ == "__main__":
	unittest.main(verbosity = 2)