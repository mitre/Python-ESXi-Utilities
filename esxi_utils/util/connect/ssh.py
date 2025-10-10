from esxi_utils.util.response import Response, ResponsePromise
from esxi_utils.util import log, exceptions
from paramiko import ssh_exception
import paramiko
import fabric
import invoke
import random
import typing
import time
import re
import os 


class _ParamikoTransportWrapper:
	"""Transparent wrapper around a paramiko transport object."""

	# We define this object in order to allow us to set the pty width and height in fabric. Fabric does not offer a native method for setting
	# the pty width/height, and instead relies on the current terminal width/height (or a small default of 80/24). Since certain functionality
	# may rely on a minimum terminal size, we require a method to set these values.
	# To achieve this, we create a transparent wrapper object around fabric's underlying paramiko transport object. For most functions,
	# this wrapper will do nothing, but for the `open_session` function we'll instead return another wrapper around the channel object.
	# By doing this, we can ultimately overwrite the channel's `get_pty` function to enforce the minimum pty width/height.
	# This monkey-patch is the simplest and most forward-compatible method to achieve this functionality without rewriting significant portions 
	# of fabric's code, or switching libraries entirely.
	# Unfortunately, setting values for this method suffers from not being thread-safe, but due to the design of fabric's ``run`` method there appears to be
	# no way to create a thread-safe solution without a significant rewrite of both fabric and invoke. Thus, these values should not be set dynamically
	# (i.e. per-command), and instead should only be set once for the entire connection lifetime.

	def __init__(self, obj: 'paramiko.Transport', min_pty_width: int, min_pty_height: int):
		self._wrapped_obj = obj
		self._min_pty_width = min_pty_width
		self._min_pty_height = min_pty_height

	def __getattr__(self, attr):
		if attr in self.__dict__:
			return getattr(self, attr)
		return getattr(self._wrapped_obj, attr)
	
	def open_session(self, *args, **kwargs):
		return _ParamikoChannelWrapper(self._wrapped_obj.open_session(*args, **kwargs), self._min_pty_width, self._min_pty_height)

	def open_channel(self, *args, **kwargs):
		return _ParamikoChannelWrapper(self._wrapped_obj.open_channel(*args, **kwargs), self._min_pty_width, self._min_pty_height)


class _ParamikoChannelWrapper:
	"""Transparent wrapper around a paramiko channel object."""
	def __init__(self, obj: 'paramiko.Channel', min_pty_width: int, min_pty_height: int):
		self._wrapped_obj = obj
		self._min_pty_width = min_pty_width
		self._min_pty_height = min_pty_height

	def __getattr__(self, attr):
		if attr in self.__dict__:
			return getattr(self, attr)
		return getattr(self._wrapped_obj, attr)
	
	def get_pty(self, term='vt100', width=80, height=24, width_pixels=0, height_pixels=0):
		width = max(self._min_pty_width, width)
		height = max(self._min_pty_height, height)
		self._wrapped_obj.get_pty(term=term, width=width, height=height, width_pixels=width_pixels, height_pixels=height_pixels)


class SSHConnection:
	"""
	A basic SSH connection to a remote host.

	:param ip: The IP of the target.
	:param username: The username to use when logging into the remote system.
	:param password: The password to use when logging into the remote system.
	:param port: The port to use when connecting over SSH.
	:param min_pty_width: The minimum width of pseudoterminals (in columns) when ``pty=True`` is set on a command.
	:param min_pty_height: The minimum height of pseudoterminals (in rows) when ``pty=True`` is set on a command.
	"""
	def __init__(self, ip: str, username: str, password: str, port: int = 22, min_pty_width: int = 160, min_pty_height: int = 48):
		os.environ['SSH_AUTH_SOCK'] = ''
		self._ip = ip
		self._username = username
		self._password = password
		self._port = port
		self._connection: typing.Optional[fabric.Connection] = None
		self._min_pty_width = min_pty_width
		self._min_pty_height = min_pty_height

	def __enter__(self):
		self.open()
		return self

	def __exit__(self, *args):
		self.close()

	def open(self):
		"""
		Open a new connection. If an connection is already open, it will be closed before opening a new one.
		"""
		if self._connection:
			self.close()
		self._connection = fabric.Connection(self._ip, user=self._username, port=self._port, connect_kwargs={ "password": self._password, "timeout": 60, "banner_timeout": 60, "auth_timeout": 60, "look_for_keys": False }, inline_ssh_env=True)
		assert self._connection.client, "Unable to get connection client"
		self._connection.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

		err = None
		for _ in range(3):
			try:
				self._connection.open()
				assert self._connection.transport, "Unable to get connection transport"
				self._connection.transport.set_keepalive(30)

				# Wrap the transport in our wrapper object
				self._connection.transport = _ParamikoTransportWrapper(self._connection.transport, self._min_pty_width, self._min_pty_height) # type: ignore
				return
			except ssh_exception.AuthenticationException as auth_err:
				self.close()
				raise auth_err
			except Exception as e:
				# Opening connections may rarely fail for various reasons, especially when the network is congested
				# Waiting a random period of time and trying again typically resolves this
				err = e
				time.sleep(random.randint(2, 5))
		self.close()
		raise exceptions.RemoteConnectionError(self, err)

	def close(self):
		"""
		Terminate the network connection to the remote end, if open.

		If no connection is open, this method does nothing.
		"""
		if self._connection:
			self._connection.close()
			self._connection = None

	def wait(self, retries: int = 60, delay: int = 2, keep_open=False) -> bool:
		"""
		Waits until this connection can be established, and then establishes the connection.

		:param retries: How many times to retry connecting before exiting. Authentication errors will terminate the wait early.
		:param delay: How long to pause between retries in seconds.
		:param keep_open: Whether or not the keep the connection open. If `True`, it is left to the user to close the connection.

		:return: Whether or not the connection could be established
		"""
		fault_tolerance = 1 # When a VM is booting, we may get false errors that resolve with time; allow this many hard failures before exiting
		retries = retries + 1
		for i in range(retries):
			if i != 0:
				time.sleep(delay)
			try:
				self.open()
				if not keep_open:
					self.close()
				return True
			except (ssh_exception.BadAuthenticationType, ssh_exception.PartialAuthentication):
				continue
			except ssh_exception.AuthenticationException as e:
				if fault_tolerance == 0:
					raise e
				else:
					fault_tolerance -= 1
					time.sleep(random.randint(20, 40))
			except Exception:
				continue
		return False

	def exec_async(
		self, 
		cmd: str, 
		stdin: typing.Optional[typing.Dict[str, str]] = None, 
		timeout: int = 120, 
		pty: bool = False,
		cwd: typing.Optional[str] = None, 
		env: typing.Optional[typing.Dict[str, typing.Any]] = None, 
		out_stream_callback: typing.Optional[typing.Callable[[str], None]] = None,
	) -> 'SSHResponsePromise':
		"""
		Execute a command asynchronously on the remote end of this connection.

		:param cmd: The command to run.
		:param stdin: A dict mapping a 'pattern' (regex string) to a 'response' (string), to input 'response' to stdin when stdout matches 'pattern'
		:param timeout: The command timeout in seconds. Set to 0 to disable timeout.
		:param pty: Run the command in a pseudoterminal. If `True`, the returned `Response` object will have a merged stdout and stderr, and stderr will be empty.
		:param cwd: The directory that the command should run in. If `None`, runs in the default directory.
		:param env: A dict of shell environment variables to be merged into the default environment that the remote command executes within.
		:param out_stream_callback: Optional callback to handle the stdout of commands. If not `None`, this will be called as a command's stdout becomes available. 

		:return: A `SSHResponsePromise` object.
		"""
		if self._connection is None:
			raise exceptions.RemoteConnectionNotOpenError(self)
		assert isinstance(cmd, str) and len(cmd.strip()) != 0, "cmd must be a non-empty string"
		assert isinstance(stdin, dict) or stdin is None, "stdin must be a dict or None"
		assert isinstance(timeout, int) and timeout >= 0, "timeout must be an integer greater or equal to 0"
		assert isinstance(pty, bool), "pty must be a boolean"
		assert callable(out_stream_callback) or out_stream_callback is None, "out_stream_callback must be a function or None"
		
		stdin = stdin or dict()
		env = env or dict()

		# Create watchers
		watchers = [ invoke.Responder(pattern=pattern, response=response) for pattern, response in stdin.items() ]

		# If out_stream_callback specified, create the handler
		out_stream = None
		if out_stream_callback:
			class OutStreamHandler:
				def flush(self):
					pass
				def write(self, s):
					if out_stream_callback:
						out_stream_callback(s)
					return len(s)
			out_stream = OutStreamHandler()
		
		log.info(f"{str(self)} Running SSH command: {cmd}")
		kwargs = { "hide": True, "warn": True, "pty": pty, "env": env, "replace_env": True, "timeout": timeout, "watchers": watchers, "out_stream": out_stream, "asynchronous": True }
		
		if cwd:
			with self._connection.cd(cwd):
				promise: invoke.runners.Promise = self._connection.run(cmd, **kwargs)
				return SSHResponsePromise(self, promise)
			
		promise: invoke.runners.Promise = self._connection.run(cmd, **kwargs)
		return SSHResponsePromise(self, promise)

	def exec(
		self, 
		cmd: str, 
		stdin: typing.Optional[typing.Dict[str, str]] = None, 
		timeout: int = 120, 
		pty: bool = False,
		cwd: typing.Optional[str] = None, 
		env: typing.Optional[typing.Dict[str, typing.Any]] = None, 
		out_stream_callback: typing.Optional[typing.Callable[[str], None]] = None,
		assert_status: typing.Optional[int] = None,
		network_retries: int = 0,
	) -> 'Response':
		"""
		Execute a command on the remote end of this connection. Unlike ``exec_async``, this will block until the associated command has finished.

		:param cmd: The command to run.
		:param stdin: A dict mapping a 'pattern' (regex string) to a 'response' (string), to input 'response' to stdin when stdout matches 'pattern'
		:param timeout: The command timeout in seconds. Set to 0 to disable timeout.
		:param pty: Run the command in a pseudoterminal. If `True`, the returned `Response` object will have a merged stdout and stderr, and stderr will be empty.
		:param cwd: The directory that the command should run in. If `None`, runs in the default directory.
		:param env: A dict of shell environment variables to be merged into the default environment that the remote command executes within.
		:param out_stream_callback: Optional callback to handle the stdout of commands. If not `None`, this will be called as a command's stdout becomes available. 
		:param assert_status: Assert that the command exits with a certain status number. If `None`, no assertion is made and checking the status is left to the caller.
		:param network_retries: Number of times to retry the command when a recoverable network error is encountered. The command should be idempotent when this is non-zero as it may run several times.

		:return: A `Response` object.
		"""
		run = lambda: self.exec_async(cmd=cmd, stdin=stdin, timeout=timeout, pty=pty, cwd=cwd, env=env, out_stream_callback=out_stream_callback).wait(assert_status)
		for _ in range(network_retries):
			try:
				return run()
			except EOFError:
				pass
		return run()
	
	def __str__(self):
		return f"<{type(self).__name__} {self._username}@{self._ip}>"

	def __repr__(self):
		return str(self)


class SSHResponsePromise(ResponsePromise):
	"""
	Encapsulates a Promise for a result of an SSH command.

	:param connection: The SSHConnection instance that generated this promise.
	:param promise: The Promise object for the command.
	"""
	def __init__(self, connection: SSHConnection, promise: invoke.runners.Promise):
		super().__init__()
		self._connection = connection
		self._promise = promise
		self._cmd = self._promise.command
		log.debug(f"New SSH Promise Object: {str(self)}")

	def wait(self, assert_status: typing.Optional[int] = None) -> Response:
		"""
		Block until the associated command exits, returning the result. 

		:param assert_status: Assert that the command exits with a certain status number. If `None`, no assertion is made and checking the status is left to the caller.
		"""
		super().wait()
		assert isinstance(assert_status, int) or assert_status is None, "assert_status must be an integer or None"
		
		resp = self._promise.join()

		stdout = resp.stdout.strip()
		stderr = resp.stderr.strip()

		# If run as sudo, remove the sudo prompt from output
		if self._cmd.startswith("sudo"):
			stdout = re.sub(r"^\[sudo\] password[^\n]+\n?", "", stdout)

		result = Response(cmd=self._cmd, stdout=stdout, stderr=stderr, status=resp.exited)
		if assert_status is not None and assert_status != result.status:
			raise exceptions.RemoteConnectionCommandError(self._connection, result)
		return result

	def cancel(self):
		"""
		Cancel the underlying operation.
		"""
		super().cancel()
		self._promise.runner.stop()
		try:
			self._promise.join()
		except invoke.exceptions.CommandTimedOut:
			pass

	def __str__(self):
		return repr(self)

	def __repr__(self):
		return f"<{type(self).__name__} for \"{self._cmd}\">"