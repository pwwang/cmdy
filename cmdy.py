VERSION = '0.0.5'

import os
import sys
import time
import threading
import subprocess
from collections import OrderedDict
from simpleconf import Config
from modkit import Modkit

Modkit().ban('os', 'sys', 'time', 'quote', 'threading', 'subprocess', 'Config', 'Queue', 'QueueEmpty', 'IS_PY3')

try:  # py3
	from shlex import quote
	from queue import Queue, Empty as QueueEmpty
	IS_PY3 = True
except ImportError:  # py2
	from pipes import quote
	from Queue import Queue, Empty as QueueEmpty
	IS_PY3 = False

DEVERR  = '/dev/stderr'
DEVOUT  = '/dev/stdout'
DEVNULL = '/dev/null'

class _Utils:

	default_config = {
		''         : [],
		'_'        : [],
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

	baked_args     = {}
	popen_arg_keys = ('_bufsize', '_executable', '_stdin', '_stdout', '_stderr', '_preexec_fn', '_close_fds', \
		'_shell', '_cwd', '_env', '_universal_newlines', '_startupinfo', '_creationflags', '_restore_signals', \
		'_start_new_session', '_pass_fds', '_encoding', '_errors', '_text')
	kw_arg_keys         = ('_sep', '_prefix', '_dupkey', '_raw')
	call_arg_keys       = ('_exe', '_okcode', '_bake', '_iter', '_pipe', '_timeout', '_bg', '_fg', '_out', '_out_', '_err', '_err_')
	call_arg_validators = (
		('_out', '_pipe', 'Cannot pipe a command with outfile specified.'),
		('_out', '_out_', 'Cannot set both _out and _out_.'),
		('_err', '_err_', 'Cannot set both _err and _err_.'),
		('_fg', '_out', 'Unable to set _out for foreground command.'),
		('_fg', '_out_', 'Unable to set _out_ for foreground command.'),
		('_fg', '_err', 'Unable to set _err for foreground command.'),
		('_fg', '_err_', 'Unable to set _err_ for foreground command.'),
		('_fg', '_iter', 'Foreground commnad is not iterrable.'),
		('_fg', '_timeout', 'Unable to count time for foreground command.'),
		('_fg', '_bg', 'Trying to iterate output which redirects to a file.'),
		('_iter', '_pipe', 'Unable to iterate a piped command.'),
	)
	piped_pool = threading.local()

	@staticmethod
	def get_piped():
		pp = _Utils.piped_pool
		if not hasattr(pp, "_piped"):
			pp._piped = []
		return pp._piped

	@staticmethod
	def parse_args(name, args, kwargs):
		"""
		Get the arguments in string, keywords (unparsed kwargs), kw_args, call_args and popen_args
		"""
		cfg = config._use(name, copy = True)
		# cmdy2 = cmdy(l = True)
		# from cmdy import ls 
		# ls() # ls -l
		cfg.update(_Utils.baked_args)
		cfg.update(kwargs)

		keywords   = {}
		kw_args    = {}
		call_args  = {}
		popen_args = {}
		for key, val in cfg.items():
			if key in _Utils.kw_arg_keys:
				kw_args[key] = val
			elif key in _Utils.call_arg_keys:
				call_args[key] = val
			elif key in _Utils.popen_arg_keys:
				popen_args[key] = val
			else:
				keywords[key] = val
		
		naked_cmds = []
		for arg in args:
			if isinstance(arg, dict):
				kwargs = kw_args.copy()
				kwargs.update({k:arg.pop(k) for k in _Utils.kw_arg_keys if k in arg})
				naked_cmds.append(_Utils.parse_kwargs(arg, kwargs))
			else:
				naked_cmds.append(quote(str(arg)))
		
		for arg1, arg2, msg in _Utils.call_arg_validators:
			if call_args.get(arg1) and call_args.get(arg2):
				raise ValueError(msg)

		return ' '.join(naked_cmds), keywords, kw_args, call_args, popen_args

	@staticmethod
	def parse_kwargs(kwargs, conf, checkraw = False):
		positional0 = kwargs.pop('', [])
		if not isinstance(positional0, (tuple, list)):
			positional0 = [positional0]
		positional1 = kwargs.pop('_', [])
		if not isinstance(positional1, (tuple, list)):
			positional1 = [positional1]

		ret    = [quote(str(pos0)) for pos0 in positional0]
		kwkeys = kwargs.keys() if isinstance(kwargs, OrderedDict) else sorted(kwargs.keys())
		for key in kwkeys:
			val = kwargs[key]
			prefix = conf['_prefix']
			if prefix == 'auto':
				prefix = '-' if len(key) == 1 else '--'
			
			sep = conf['_sep']
			if sep == 'auto':
				sep = ' ' if len(key) == 1 else '='

			if checkraw and not conf['_raw']:
				key = key.replace('_', '-')

			if isinstance(val, bool):
				if not val:
					continue
				else:
					ret.append('{prefix}{key}'.format(prefix = prefix, key = key))
			elif isinstance(val, (tuple, list)):
				if not conf['_dupkey']:
					ret.append('{prefix}{key}{sep}{vals}'.format(
						prefix = prefix, key  = key,
						sep    = sep,    vals = ' '.join(quote(str(v)) for v in val)
					))
				else:
					ret.extend('{prefix}{key}{sep}{v}'.format(
						prefix = prefix, key = key,
						sep    = sep,    v   = quote(str(v))
					) for v in val)
			else:
				ret.append('{prefix}{key}{sep}{val}'.format(prefix = prefix, key = key, sep = sep, val = quote(str(val))))

		ret.extend(quote(str(pos1)) for pos1 in positional1)

		return ' '.join(ret)

config = Config()
config._load(dict(default = _Utils.default_config), '~/.cmdy.ini', './.cmdy.ini', 'CMDY.osenv')

class Cmdy(object):

	def __init__(self, exe, cmd = '', keywords = None, kw_args = None, call_args = None, popen_args = None):
		self._exe = exe
		self._cmd = cmd
		self.keywords   = keywords or {}
		self.kw_args    = kw_args or {}
		self.call_args  = call_args or {}
		self.popen_args = popen_args or {}

	def __call__(self, *args, **kwargs):
		
		naked_cmd, keywords0, kw_args0, call_args0, popen_args0 = _Utils.parse_args(self._exe, args, kwargs)

		keywords   = self.keywords.copy()
		kw_args    = self.kw_args.copy()
		call_args  = self.call_args.copy()
		popen_args = self.popen_args.copy()
		keywords.update(keywords0)
		kw_args.update(kw_args0)
		call_args.update(call_args0)
		popen_args.update(popen_args0)

		if call_args.pop('_bake', False):
			return self.__class__(
				self._exe, ' '.join(filter(None, [self._cmd, naked_cmd])),
				keywords   = keywords,
				kw_args    = kw_args,
				call_args  = call_args,
				popen_args = popen_args
			)
			
		exe       = call_args.get('_exe', self._exe) or self._exe
		cmd_parts = [quote(exe), self._cmd, naked_cmd, _Utils.parse_kwargs(keywords, kw_args, True)]
		cmd       = ' '.join(filter(None, cmd_parts))
		return CmdyResult(cmd, call_args, popen_args)

	def bake(self, *args, **kwargs):
		kwargs['_bake'] = True
		return self(*args, **kwargs)

	def __getattr__(self, subcmd):
		return self.__class__(self._exe, ' '.join(filter(None, [self._cmd, subcmd])))

class CmdyTimeoutException(Exception):
	def __init__(self, cmdy):
		self.cmdy = cmdy
		msg  = 'Command not finished in %s second(s).\n\n' % cmdy.call_args['_timeout']
		msg += '  [PID] %s' % cmdy.pid
		msg += '\n'
		msg += '  [CMD] %s' % cmdy.cmd
		msg += '\n'
		super(CmdyTimeoutException, self).__init__(msg)

class CmdyReturnCodeException(Exception):

	def __init__(self, cmdy):
		self.cmdy = cmdy
		msg  = 'Unexpected RETURN CODE %s, expecting: %s\n' % (cmdy.rc, cmdy.call_args['_okcode'])
		msg += '\n' 
		msg += '  [PID]    %s\n' % (cmdy.pid if cmdy.pid and cmdy.rc != -1 else 'Not launched.')
		msg += '\n'
		msg += '  [CMD]    %s\n' % cmdy.cmd 
		msg += '\n'
		if cmdy.call_args['_iter']:
			msg += '  [STDOUT] <ITERRATED>\n'
		else:
			outs = cmdy.stdout.splitlines()
			msg += '  [STDOUT] %s\n' % (outs.pop().rstrip('\n') if outs else '')
			for out in outs[:31]:
				msg += '           %s\n' % out.rstrip('\n')
			if len(outs) > 32:
				msg += '           [%s line(s) hidden.]\n' % (len(outs) - 32)

		msg += '\n'

		errs = cmdy.stderr.splitlines()
		msg += '  [STDERR] %s\n' % (errs.pop().rstrip('\n') if errs else '')
		for err in errs[:31]:
			msg += '           %s\n' % err.rstrip()
		if len(errs) > 32:
			msg += '           [%s line(s) hidden.]\n' % (len(errs) - 32)
		msg += '\n'
		super(CmdyReturnCodeException, self).__init__(msg)

class CmdyResult(object):

	def __init__(self, cmd, call_args, popen_args):
		self.done        = False
		self.p           = None
		self.popen_args  = {
			key[1:]:val for key, val in popen_args.items() 
			if IS_PY3 or key not in ('_restore_signals', '_start_new_session', '_pass_fds', '_encoding', '_errors', '_text')
		}
		self.call_args   = call_args
		self.should_wait = True
		self.should_run  = True
		self.rc          = 0
		self.pid         = 0
		self.cmd         = cmd
		self.iterq       = Queue()
		self._stdout     = ''
		self._stderr     = ''
		self._piped      = None

		okcode = self.call_args['_okcode']
		if isinstance(okcode, int):
			okcode = [okcode]
		elif not isinstance(okcode, list):
			okcode = okcode.split(',')

		self.call_args['_okcode'] = [oc if isinstance(oc, int) else int(oc.strip()) for oc in okcode]

		# put the arguments in right type
		self.call_args['_timeout'] = float(self.call_args['_timeout'])
		for key in ('_dupkey', '_bake', '_iter', '_pipe', '_raw' , '_bg', '_fg'):
			if not key in self.call_args or isinstance(self.call_args[key], bool):
				continue
			self.call_args[key] = self.call_args[key] in ('True', 'TRUE', 'T', 't', 'true', 1, '1')

		if call_args['_fg']:
			self.popen_args['stdout'] = sys.stdout
			self.popen_args['stderr'] = sys.stderr
		else:
			_out  = call_args.get('_out')
			_out_ = call_args.get('_out_')
			_err  = call_args.get('_err')
			_err_ = call_args.get('_err_')

			outpipe = self.popen_args.get('stdout', subprocess.PIPE)
			errpipe = self.popen_args.get('stderr', subprocess.PIPE)

			if not _out and not _out_:
				self.popen_args['stdout'] = outpipe
			elif _out == '>':
				self.popen_args['stdout'] = outpipe
				self.call_args['_iter']   = 'out'
			elif _out:
				self.popen_args['stdout'] = open(_out, 'w')
			else: #elif _out_:
				self.popen_args['stdout'] = open(_out_, 'a')
			
			if not _err and not _err_:
				self.popen_args['stderr'] = errpipe
			elif _err == '>':
				self.popen_args['stderr'] = errpipe
				self.call_args['_iter']   = 'err'
			elif _err:
				self.popen_args['stderr'] = open(_err, 'w')
			else: #if _err_:
				self.popen_args['stderr'] = open(_err_, 'a')

		if _Utils.get_piped():
			self.should_run = False

		if call_args['_pipe']:
			_Utils.get_piped().append(self)
			self.should_wait = False

		if self.should_run:
			self.run()

	def __del__(self):
		if self.p and self.p.stdout:
			if hasattr(self.p.stdout, 'close') and callable(self.p.stdout.close):
				self.p.stdout.close()
		if self.p and self.p.stderr:
			if hasattr(self.p.stderr, 'close') and callable(self.p.stderr.close):
				self.p.stderr.close()
		if self.popen_args['stdout'] and hasattr(self.popen_args['stdout'], 'close') and \
			callable(self.popen_args['stdout'].close):
			self.popen_args['stdout'].close()
		if self.popen_args['stderr'] and hasattr(self.popen_args['stderr'], 'close') and \
			callable(self.popen_args['stderr'].close):
			self.popen_args['stderr'].close()

	def __add__(self, other):
		return str(self) + other

	def __contains__(self, other):
		return other in str(self)

	def __eq__(self, other):
		return str(self) == other

	def __ne__(self, other):
		return not self.__eq__(other)

	def int(self):
		return int(self.strip())

	def float(self):
		return float(self.strip())
	
	def __getattr__(self, name):
		# attach str methods
		if name in ('capitalize', 'center', 'count', 'decode', 'encode', 'endswith', 'expandtabs', \
			'find', 'format', 'index', 'isalnum', 'isalpha', 'isdigit', 'islower', 'isspace', \
			'istitle', 'isupper', 'join', 'ljust', 'lower', 'lstrip', 'partition', 'replace', \
			'rfind', 'rindex', 'rjust', 'rpartition', 'rsplit', 'rstrip', 'split', 'splitlines', \
			'startswith', 'strip', 'swapcase', 'title', 'translate', 'upper', 'zfill'):
			return getattr(str(self), name)
		raise AttributeError('No such attribute "%s" for CmdyResult.' % name)

	def reset(self):
		self.done        = False
		self.p           = None
		self.should_wait = True
		self.should_run  = True
		self.rc          = 0
		self._stdout     = ''
		self._stderr     = ''
		
	def run(self):
		if self.done:
			return

		self.done = True
		self.p    = subprocess.Popen(self.cmd, shell = True, **self.popen_args)
		self.pid  = self.p.pid
		if self.should_wait:
			self._wait()

	def post_handling(self):
		"""
		Deal with stuff after jobs being submitted
		"""
		t0 = time.time()
		while True:
			# _iter, _bg, _timeout
			if self.call_args['_iter']:
				line = (self.p.stdout, self.p.stderr)[
					int(self.call_args['_iter'] == 'err')
				].readline()
				if line:
					self.iterq.put(line)
				elif self.p.poll() is not None:
					break
				time.sleep(.1)
				if self.call_args['_timeout'] and time.time() - t0 > self.call_args['_timeout']:
					self.p.terminate()
					# to eliminate ResourceWarning from python3
					self.p.wait()
					raise CmdyTimeoutException(self)
				continue
			elif self.call_args['_timeout']:
				if self.p.poll() is None:
					time.sleep(.1)
					if time.time() - t0 > self.call_args['_timeout']:
						self.p.terminate()
						# to eliminate ResourceWarning from python3
						self.p.wait()
						raise CmdyTimeoutException(self)
				else:
					break
			else:
				break

		if self.call_args['_iter']:
			self.iterq.put(None)

		# wait for all _piped, to eliminate ResourceWarning from python3
		piped = self._piped
		while piped:
			piped.p.wait()
			piped = piped._piped

		self.rc = self.p.wait()
		self.raise_rc()

		if callable(self.call_args['_bg']):
			self.call_args['_bg'](self)

	def post_handling_bg(self):
		thr = threading.Thread(target = self.post_handling)
		thr.daemon = True
		thr.start()

	def raise_rc(self):
		if self.rc in self.call_args['_okcode']:
			return
		raise CmdyReturnCodeException(self)

	def wait(self):
		"""
		Function for user to call
		"""
		self.rc = self.p.wait() if self.p else -1
		self.raise_rc()

	def _wait(self):
		if not self.p:
			self.rc = -1
			self.raise_rc()
		elif self.call_args['_fg']:
			self.rc = self.p.wait()
			self.raise_rc()
		elif self.call_args['_bg']:
			self.post_handling_bg()
		else:
			self.post_handling()
		
	def next(self):
		if not self.done:
			raise RuntimeError('Command not started to run yet.')
		elif not self.p:
			raise RuntimeError('Failed to open a process.')
		elif self.call_args['_iter'] == 'err' and not self.p.stderr:
			raise RuntimeError('No stderr captured, may be redirected.')
		elif  self.call_args['_iter'] in (True, 'out') and not self.p.stdout:
			raise RuntimeError('No stdout captured, may be redirected.')
		elif not self.call_args['_iter']:
			raise RuntimeError('CmdyResult is not iterrable with _iter = False.')
		
		try:
			item = self.iterq.get()
		except QueueEmpty:
			return None
		if item is None:
			raise StopIteration()
		return item

	__next__ = next

	def __iter__(self):
		return self

	@property
	def stdout(self):
		if not self.done:
			raise RuntimeError('Command not started to run yet.')
		elif self.call_args['_fg']:
			return ''
		elif not self.p:
			raise RuntimeError('Failed to open a process.')
		elif self.call_args['_bg'] and self.p.poll() is None:
			raise RuntimeError('Background command has not finished yet.')
		elif not self.p.stdout:
			raise RuntimeError('No stdout captured, may be redirected.')
		elif self.call_args['_iter']:
			return self
		elif not self._stdout:
			self._stdout = self.p.stdout.read()
		return self._stdout

	@property
	def stderr(self):
		if not self.done:
			raise RuntimeError('Command not starts to run yet.')
		elif not self.p:
			raise RuntimeError('Failed to open a process.')
		elif self.call_args['_bg'] and self.p.poll() is None:
			raise RuntimeError('Background command has not finished yet.')
		elif not self.p.stderr:
			raise RuntimeError('No stderr captured, may be redirected.')
		elif not self._stderr:
			self._stderr = self.p.stderr.read()
		return self._stderr
		
	def __str__(self):
		return self.stdout

	def __repr__(self):
		return str(self)

	def __bool__(self):
		return self.rc == 0

	def __or__(self, other):
		assert self.popen_args['stdout'] is subprocess.PIPE
		assert self.call_args['_pipe'] is True
		cmd = _Utils.get_piped().pop(0)
		assert self is cmd
		other.popen_args['stdin'] = self.p.stdout
		other._piped = self
		other.run()
		#self.p.wait()
		return other

	def __gt__(self, outfile):
		assert self.call_args.get('_out') == '>' or self.call_args.get('_err') == '>'
		with open(outfile, 'w') as f:
			for line in self:
				f.write(line)
	
	def __rshift__(self, outfile):
		assert self.call_args.get('_out') == '>' or self.call_args.get('_err') == '>'
		with open(outfile, 'a') as f:
			for line in self:
				f.write(line)

def _modkit_delegate(exe):
	return Cmdy(exe)

def _modkit_call(module, **kwargs):
	module._Utils.baked_args.update(kwargs)
	return module

