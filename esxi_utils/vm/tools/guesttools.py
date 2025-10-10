from esxi_utils.util.response import Response, ResponsePromise
from esxi_utils.util import exceptions, decorators
from contextlib import contextmanager
from esxi_utils.util import log
import urllib.request
import threading
import pyVmomi
import random
import typing
import time
import ssl
import re

if typing.TYPE_CHECKING:
	from esxi_utils.vm.virtualmachine import VirtualMachine

class GuestTools:
	"""
	Wrapper class for functionality related to VMware Tools on a Virtual Machine. The virtual machine must have VMware tools installed for
	any of the contained functions to work.

	:param vm: A `VirtualMachine` object to wrap. VMware tools must be installed on this virtual machine.
	"""
	def __init__(self, vm: 'VirtualMachine'):
		self._vm = vm
		self._vim_vm = self._vm._vim_vm

	@property
	def running(self) -> bool:
		"""
		Whether or not this Virtual Machine has guest tools running.
		"""
		return self._vim_vm.guest.toolsRunningStatus == "guestToolsRunning"

	def wait(self, retries: int = 120, delay: int = 2) -> bool:
		"""
		Wait for the guest tools to be in the running state.

		:param retries: How many times to retry before exiting.
		:param delay: How long to pause between retries (in seconds).

		:return: A boolean whether or not the state was reached in the allotted amount of retries.
		"""
		for attempt in range(1, retries+1):
			if self.running:
				return True
			log.debug(f"{str(self)} {attempt} failed attempts to connect to guesttools")
			time.sleep(delay)
		return False

	def _assert_available(self):
		"""
		Assert that guest tools is in the running state. This will wait for a small period of time for guest tools to be available,
		and will raise an exception if guest tools does not become available in this timeframe.
		"""
		if not self.wait(retries=30, delay=1):
			raise exceptions.GuestToolsError(self._vm, "VMWare tools is not available or not running")

	def execute_program_async(
		self, 
		username: str, 
		password: str, 
		command: str, 
		cwd: typing.Optional[str] = None, 
		make_output_available: bool = True,
		out_stream_callback: typing.Optional[typing.Callable[[str], None]] = None
	)  -> 'GuestToolsResponsePromise':
		"""
		Runs a program in the guest operating system asynchronously.

		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.
		:param command: The command to run. This command should use the full path to the program, e.g. `/usr/bin/date` rather than `date`
		:param cwd: The working directory that the command should be run in.
		:param make_output_available: Whether or not to attempt to make output available by running the command with stdout/stderr redirects. This may not work for all operating
		  systems and is therefore left as an optional feature. 
		:param out_stream_callback: Optional callback to handle the stdout of commands. If not `None`, this will be called as a command's stdout becomes available. 

		:return: A `GuestToolsResponsePromise` object.
		"""
		return GuestToolsResponsePromise(
			tools=self, 
			username=username, 
			password=password, 
			command=command, 
			cwd=cwd, 
			make_output_available=make_output_available,
			out_stream_callback=out_stream_callback
		)

	def execute_program(
		self, 
		username: str, 
		password: str, 
		command: str, 
		cwd: typing.Optional[str] = None,
		timeout: typing.Optional[int] = 120,
		assert_status: typing.Optional[int] = None,
		make_output_available: bool = True,
		out_stream_callback: typing.Optional[typing.Callable[[str], None]] = None
	) -> 'Response':
		"""
		Runs a program in the guest operating system. Unlike ``execute_program_async``, this will block until the associated command has finished.

		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.
		:param command: The command to run. This command should use the full path to the program, e.g. `/usr/bin/date` rather than `date`
		:param cwd: The working directory that the command should be run in.
		:param timeout: The command timeout in seconds. Set to 0 or `None` to disable timeout.
		:param assert_status: Assert that the command exits with a certain status number. If `None`, no assertion is made and checking the status is left to the caller.
		:param make_output_available: Whether or not to attempt to make output available by running the command with stdout/stderr redirects. This may not work for all operating
		  systems and is therefore left as an optional feature. 
		:param out_stream_callback: Optional callback to handle the stdout of commands. If not `None`, this will be called as a command's stdout becomes available. 

		:return: A `Response` object
		"""
		return self.execute_program_async(
			username=username, 
			password=password, 
			command=command, 
			cwd=cwd, 
			make_output_available=make_output_available,
			out_stream_callback=out_stream_callback
		).wait(assert_status=assert_status, timeout=timeout)

	@decorators.retry_on_error([pyVmomi.vim.fault.InvalidState], pause_between_attempts=(0.5, 5.0))
	def list_files(self, username: str, password: str, filepath: str) -> typing.List[str]:
		"""
		List files and directories in the given filepath in the guest operating system. 

		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.
		:param filepath: The filepath to list.

		:return: A list of files and directories in `filepath`.
		"""
		self._assert_available()

		def get_files_object(path, index):
			return self._service_content.guestOperationsManager.fileManager.ListFilesInGuest(
				vm=self._vim_vm,
				auth=self._get_auth(username=username, password=password),
				filePath=path,
				index=index,
			)

		# First resolve symlinks
		files_object = None
		while True:
			files_object = get_files_object(filepath, 0)
			if len(files_object.files) == 1 and files_object.files[0].type == "symlink":
				filepath = files_object.files[0].attributes.symlinkTarget
			else:
				break

		# Begin reading the files
		# We need to paginate since large responses will result in an error
		files = [ f.path for f in files_object.files ]
		while files_object.remaining != 0:
			files_object = get_files_object(filepath, len(files))
			files.extend([ f.path for f in files_object.files ])

		return [ file for file in files if file not in [".", ".."]]

	@decorators.retry_on_error([pyVmomi.vim.fault.InvalidState], pause_between_attempts=(0.5, 5.0))
	def get_file(self, username: str, password: str, filepath: str, encoding: typing.Optional[str] = "utf-8") -> typing.Union[str, bytes]:
		"""
		Get the content of a file at the given filepath in the guest operating system.

		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.
		:param filepath: The filepath of the file to get.
		:param encoding: The encoding to use when reading the file. If `None`, the raw bytes will instead be returned.

		:return: The contents of the file as a string (or bytes if `encoding=None`)
		"""
		self._assert_available()
		info = self._service_content.guestOperationsManager.fileManager.InitiateFileTransferFromGuest(
			vm=self._vim_vm,
			auth=self._get_auth(username=username, password=password),
			guestFilePath=filepath,
		)

		ctx = ssl.create_default_context()
		ctx.check_hostname = False
		ctx.verify_mode = ssl.CERT_NONE

		url = info.url.replace("*", self._vm._client.hostname)
		try:
			with urllib.request.urlopen(url, context=ctx) as response:
				response_content = response.read()
				if not response.status == 200:
					raise exceptions.GuestToolsError(self._vm, f"Unable to get file {filepath} (status {response.status}): {response_content}")
				if encoding:
					return response_content.decode(encoding=encoding)
				return response_content
		except (urllib.error.URLError, urllib.error.HTTPError) as error:
			raise exceptions.GuestToolsError(self._vm, f"Unable to get file {filepath}: {error.reason}")

	@decorators.retry_on_error([pyVmomi.vim.fault.InvalidState], pause_between_attempts=(0.5, 5.0))
	def write_file(self, username: str, password: str, filepath: str, data: typing.Union[str, bytes]):
		"""
		Write data to a file at the given filepath in the guest operating system.

		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.
		:param filepath: The filepath of the file to write to. The file will be created if it does not exist, or will be overwritten if it does exist.
		:param data: The data to write to the file specified by `filepath`
		"""
		self._assert_available()
		if isinstance(data, str):
			data = str.encode(data)

		url = self._service_content.guestOperationsManager.fileManager.InitiateFileTransferToGuest(
			vm=self._vim_vm,
			auth=self._get_auth(username=username, password=password),
			guestFilePath=filepath,
			fileAttributes=pyVmomi.vim.vm.guest.FileManager.FileAttributes(),
			fileSize=len(data),
			overwrite=True
		)
		url = url.replace("*", self._vm._client.hostname)

		ctx = ssl.create_default_context()
		ctx.check_hostname = False
		ctx.verify_mode = ssl.CERT_NONE

		try:
			# Note: Guest Tools does not appear to allow streaming for files
			# Therefore, the input to `data` for urlopen must be a byte array and not a file-like object
			with urllib.request.urlopen(urllib.request.Request(url, data=data, method='PUT'), context=ctx) as response:
				response_content = response.read()
				if not response.status == 200:
					raise exceptions.GuestToolsError(self._vm, f"Unable to write file {filepath} (status {response.status}): {response_content}")
		except (urllib.error.URLError, urllib.error.HTTPError) as error:
			raise exceptions.GuestToolsError(self._vm, f"Unable to write file {filepath}: {error.reason}")

	@decorators.retry_on_error([pyVmomi.vim.fault.InvalidState], pause_between_attempts=(0.5, 5.0))
	def delete_file(self, username: str, password: str, filepath: str):
		"""
		Delete a file in the guest operating system.

		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.
		:param filepath: The filepath of the file to delete.
		"""
		self._assert_available()
		self._service_content.guestOperationsManager.fileManager.DeleteFileInGuest(
			vm=self._vim_vm,
			auth=self._get_auth(username=username, password=password),
			filePath=filepath
		)

	@decorators.retry_on_error([pyVmomi.vim.fault.InvalidState], pause_between_attempts=(0.5, 5.0))
	def delete_directory(self, username: str, password: str, dirpath: str, recursive: bool = False):
		"""
		Delete a directory in the guest operating system.

		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.
		:param dirpath: The path of the directory to delete.
		:param recursive: If true, all subdirectories are also deleted. If false, the directory must be empty for the operation to succeed. 
		"""
		self._assert_available()
		self._service_content.guestOperationsManager.fileManager.DeleteDirectoryInGuest(
			vm=self._vim_vm,
			auth=self._get_auth(username=username, password=password),
			directoryPath=dirpath,
			recursive=recursive
		)

	@decorators.retry_on_error([pyVmomi.vim.fault.InvalidState], pause_between_attempts=(0.5, 5.0))
	def create_temporary_file(self, username: str, password: str, extension: str = "") -> str:
		"""
		Creates a new unique temporary file for the user to use as needed. The user is responsible for removing it when it is no longer needed. 
		A guest-specific location will be used.

		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.
		:param extension: The extension to give to the new temporary file. 

		:return: The absolute path of the temporary file that is created.
		"""
		self._assert_available()
		extension = f".{extension}" if not extension.startswith(".") else extension
		return self._service_content.guestOperationsManager.fileManager.CreateTemporaryFileInGuest(
			vm=self._vim_vm,
			auth=self._get_auth(username=username, password=password),
			prefix="",
			suffix=extension
		)

	@decorators.retry_on_error([pyVmomi.vim.fault.InvalidState], pause_between_attempts=(0.5, 5.0))
	def create_temporary_directory(self, username: str, password: str, prefix: str = "", suffix: str = "") -> str:
		"""
		Creates a new unique temporary directory for the user to use as needed. The user is responsible for removing it when it is no longer needed. 
		A guest-specific location will be used.

		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.
		:param prefix: The prefix to give to the new temporary directory. 
		:param suffix: The suffix to give to the new temporary directory. 

		:return: The absolute path of the temporary directory that is created.
		"""
		self._assert_available()
		return self._service_content.guestOperationsManager.fileManager.CreateTemporaryDirectoryInGuest(
			vm=self._vim_vm,
			auth=self._get_auth(username=username, password=password),
			prefix=prefix,
			suffix=suffix
		)

	@contextmanager
	def use_temporary_directory(self, username: str, password: str, prefix: str = "", suffix: str = "") -> typing.Generator[str, None, None]:
		"""
		Creates a new unique temporary directory for the user to use as needed. The directory is created as a context manager (`with` statement)
		and will be deleted (along with all contents) when the context is completed. A guest-specific location will be used.

		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.
		param prefix: The prefix to give to the new temporary directory. 
		:param suffix: The suffix to give to the new temporary directory. 

		:return: The absolute path of the temporary directory that is created.
		"""
		self._assert_available()
		path = self.create_temporary_directory(username=username, password=password, prefix=prefix, suffix=suffix)
		try:
			yield path
		finally:
			success = False
			for _ in range(20):
				try:
					self.delete_directory(username=username, password=password, dirpath=path, recursive=True)
					success = True
					break
				except Exception:
					time.sleep(5)

			if not success:
				self.delete_directory(username=username, password=password, dirpath=path, recursive=True)

	@contextmanager
	def use_temporary_file(self, username: str, password: str, extension: str = "") -> typing.Generator[str, None, None]:
		"""
		Creates a new unique temporary file for the user to use as needed. The file is created as a context manager (`with` statement)
		and will be deleted when the context is completed. A guest-specific location will be used.

		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.
		:param extension: The extension to give to the new temporary file. 

		:return: The absolute path of the temporary file that is created.
		"""
		self._assert_available()
		path = self.create_temporary_file(username=username, password=password, extension=extension)
		try:
			yield path
		finally:
			success = False
			for _ in range(20):
				try:
					self.delete_file(username=username, password=password, filepath=path)
					success = True
					break
				except Exception:
					time.sleep(5)

			if not success:
				self.delete_file(username=username, password=password, filepath=path)

	def reboot(self):
		"""
		Perform an ESXi reboot of the VM (soft reboot).
		"""
		self._assert_available()
		self._vim_vm.RebootGuest()

	def shutdown(self):
		"""
		Perform a clean shutdown of the VM.
		"""
		self._assert_available()
		self._vim_vm.ShutdownGuest()

	@property
	def networks(self) -> typing.List[typing.Dict[str, typing.Any]]:
		"""
		Get information on the networks for this VM, as reported by guest tools.
		"""
		self._assert_available()
		data = []
		for nicinfo in self._vim_vm.guest.net:
			obj = {
				"network": nicinfo.network,
				"ips": [ ip for ip in nicinfo.ipAddress if re.match(r"^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$", ip) ],
				"mac": nicinfo.macAddress,
				"connected": nicinfo.connected,
			}
			data.append(obj)
		return data
			
	def ip(self, network: str) -> typing.Union[str, None]:
		"""
		Get the IP of this VM on a specific network, as reported by guest tools.

		:param network: The name of the network.

		:return: The IP, if found, or `None` if not found.
		"""
		self._assert_available()
		for network_data in self.networks:
			if network_data["network"] == network and len(network_data["ips"]) > 0:
				return network_data["ips"][0]
		return None

	def _get_auth(self, username: str, password: str):
		"""
		Get the `NamePasswordAuthentication` object for the username/password.

		:param username: The username to use.
		:param password: The password to use.

		:return: The `NamePasswordAuthentication` object.
		"""
		return pyVmomi.vim.vm.guest.NamePasswordAuthentication(username=username, password=password)

	@property
	def _service_content(self):
		"""
		Get the `ServiceContent` object for the current service instance.

		:return: A `ServiceContent` object.
		"""
		return self._vm._client._service_instance.RetrieveContent()

	def __str__(self):
		return f"<{type(self).__name__} for {self._vm.name}>"

	def __repr__(self):
		return str(self)
	

class GuestToolsResponsePromise(ResponsePromise):
	"""
	Encapsulates a Promise for a result of an GuestTools command.

	:param tools: The GuestTools instance from which this promise originates.
	:param username: The username of the virtual machine user.
	:param password: The password of the virtual machine user.
	:param command: The command to run. This command should use the full path to the program, e.g. `/usr/bin/date` rather than `date`
	:param cwd: The working directory that the command should be run in.
	:param make_output_available: Whether or not to attempt to make output available by running the command with stdout/stderr redirects. This may not work for all operating
	  systems and is therefore left as an optional feature. 
	:param out_stream_callback: Optional callback to handle the stdout of commands. If not `None`, this will be called as a command's stdout becomes available. 
	"""

	_tools: GuestTools = None
	"""The GuestTools object to which this promise belongs."""

	_username: str = None
	"""The username for the virtual machine."""

	_password: str = None
	"""The password for the virtual machine."""

	_command: str = None
	"""The original command passed to this promise."""

	_cwd: str = None
	"""The working directory for the command to run."""

	_out_stream_callback: typing.Optional[typing.Callable[[str], None]] = None
	"""The callback to call when stdout becomes available."""

	_stdoutfile: typing.Optional[str] = None
	"""The file to which stdout will be written. If not ``None``, stdout will be continuously read from this file and this file will be deleted when the promise completes."""

	_stderrfile: typing.Optional[str] = None
	"""The file to which stderr will be written. If not ``None``, stderr will be continuously read from this file and this file will be deleted when the promise completes."""

	_pid: int = None
	"""The process ID for the running process."""

	_resp: typing.Optional[Response] = None
	"""The response of the resolved promise."""

	_exception: typing.Optional[Exception] = None
	"""The exception of the resolved promise."""

	_thread_alive: bool = True
	"""Whether the promise thread should currently be running."""

	_thread: threading.Thread = None
	"""The promise thread."""

	# Based on https://github.com/vmware/vsphere-guest-run
	def __init__(
		self, 
		tools: GuestTools, 
		username: str, 
		password: str, 
		command: str, 
		cwd: typing.Optional[str] = None, 
		make_output_available: bool = True, 
		out_stream_callback: typing.Optional[typing.Callable[[str], None]] = None
	):
		super().__init__()
		assert isinstance(username, str), "username must be a string"
		assert isinstance(password, str), "password must be a string"
		assert isinstance(command, str), "command must be a string"
		assert isinstance(cwd, str) or cwd is None, "cwd must be a string or None"
		assert isinstance(make_output_available, bool), "make_output_available must be a boolean"
		assert callable(out_stream_callback) or out_stream_callback is None, "out_stream_callback must be a function or None"
		tools._assert_available()

		self._tools = tools
		self._username = username
		self._password = password
		self._command = command
		self._cwd = cwd
		self._out_stream_callback = out_stream_callback

		# Format arguments
		new_command = self._setup(make_output_available=make_output_available)
		tokens = new_command.split()
		program_path = tokens.pop(0)
		arguments = ''
		for token in tokens:
			arguments += f" {token}"

		# Start the process
		program_spec = pyVmomi.vim.vm.guest.ProcessManager.ProgramSpec(programPath=program_path, arguments=arguments, workingDirectory=self._cwd)
		process_manager = self._tools._service_content.guestOperationsManager.processManager
		creds = self._tools._get_auth(username=username, password=password)

		@decorators.retry_on_error([pyVmomi.vim.fault.InvalidState], pause_between_attempts=(0.5, 5.0))
		def start_program() -> int:
			return process_manager.StartProgramInGuest(self._tools._vim_vm, creds, program_spec)

		self._pid = start_program()
		self._thread = threading.Thread(target=self._run)
		self._thread.start()
		log.debug(f"New GuestTools Promise Object: {str(self)}")

	def _setup(self, make_output_available: bool = False) -> str:
		"""
		Perform any setup necessary prior to starting the command.

		:param make_output_available: Whether or not it is requested to make the output of the command available.
		
		:return: The command to run.
		"""
		command = self._command

		# Handle stdout/stderr
		if make_output_available:
			self._stdoutfile = self._tools.create_temporary_file(self._username, self._password, ".out")
			self._stderrfile = self._tools.create_temporary_file(self._username, self._password, ".err")
			command = f"{command} > {self._stdoutfile} 2> {self._stderrfile}"

		return command

	def _run(self):
		"""
		Main thread.
		"""
		creds = self._tools._get_auth(username=self._username, password=self._password)
		process_manager = self._tools._service_content.guestOperationsManager.processManager
		error_tolerance = 10
		last_stdout = ""
		try:
			# Monitor the process to periodically check if it has completed
			while self._thread_alive:
				try:
					processes = process_manager.ListProcessesInGuest(self._tools._vim_vm, creds, [self._pid])
					if len(processes) == 0:
						raise exceptions.GuestToolsError(self._tools._vm, f"Process not found (pid={self._pid})")
				except Exception as e:
					if error_tolerance == 0:
						raise e
					error_tolerance -= 1
					time.sleep(random.uniform(0.5, 5))
					continue

				process = processes[0]

				# Capture output if requested
				if self._out_stream_callback:
					stdout, _ = self._output()
					new_stdout = stdout[len(last_stdout):]
					if len(new_stdout):
						self._out_stream_callback(new_stdout)
					last_stdout = stdout

				# Check if finished
				if process.exitCode is None:
					time.sleep(random.uniform(0.5, 3))
					error_tolerance = 10
					continue

				# Done
				stdout, stderr = self._output()
				self._resp = self._format_response(Response(cmd=self._command, stdout=stdout, stderr=stderr, status=process.exitCode))
				self._thread_alive = False
		except Exception as e:
			self._exception = e
		finally:
			self._thread_alive = False
			self._cleanup()

	def _format_response(self, response: Response) -> Response:
		"""
		Perform post-processing on a result. This will occur when a command finishes executing but before any files are cleaned up.

		:param response: The result of the command.

		:return: The new result.
		"""
		return response

	def wait(self, assert_status: typing.Optional[int] = None, timeout: typing.Optional[int] = 120) -> Response:
		"""
		Block until the associated command exits, returning the result. 
		
		:param assert_status: Assert that the command exits with a certain status number. If `None`, no assertion is made and checking the status is left to the caller.
		:param timeout: The command timeout in seconds. Set to 0 or `None` to disable timeout.
		"""
		super().wait()
		assert isinstance(assert_status, int) or assert_status is None, "assert_status must be an integer or None"
		assert isinstance(timeout, int) or timeout is None, "timeout must be an integer or None"

		if self._thread_alive:
			self._thread.join(timeout if timeout > 0 else None)
			if self._thread.is_alive():
				# Timed out
				self._terminate()
				self._cleanup()
				raise TimeoutError(f"{str(self)} Guest command \"{self._command}\" timed out after {str(timeout)} seconds")
			
		if self._exception:
			raise self._exception
		
		if assert_status is not None and self._resp and self._resp.status != assert_status:
			raise exceptions.GuestToolsError(self._tools._vm, f"Command failed: {str(self._resp)}")

		return self._resp

	def cancel(self):
		"""
		Cancel the underlying operation.
		"""
		super().cancel()
		self._thread_alive = False
		self._thread.join()
		self._terminate()
		self._cleanup()

	def _terminate(self):
		"""
		Forcefully terminate the underyling process.
		"""
		creds = self._tools._get_auth(username=self._username, password=self._password)
		process_manager = self._tools._service_content.guestOperationsManager.processManager
		@decorators.retry_on_error([pyVmomi.vim.fault.InvalidState], pause_between_attempts=(0.5, 5.0))
		def terminate():
			process_manager.TerminateProcessInGuest(self._tools._vim_vm, creds, self._pid)

		try:
			terminate()
		except pyVmomi.vim.fault.GuestProcessNotFound as e1:
			log.debug(f'Caught vim.fault.GuestProcessNotFound exception from pyVmomi: {str(e1)}')
		except BaseException as e:
			if not str(e).startswith('process not found ('):
				raise exceptions.GuestToolsError(self._tools._vm, f"Failed to terminate process for \"{self._command}\": {str(e)}")

	def _cleanup(self):
		"""
		Clean up any files or other resources after the process has finished.
		"""
		if self._stdoutfile:
			self._tools.delete_file(self._username, self._password, self._stdoutfile)
			self._stdoutfile = None
		if self._stderrfile:
			self._tools.delete_file(self._username, self._password, self._stderrfile)
			self._stderrfile = None

	def _output(self) -> typing.Tuple[str, str]:
		"""
		Get the current stdout/stderr output.

		:return: A tuple (stdout, stderr)
		"""
		stdout = ""
		stderr = ""
		if self._stdoutfile:
			stdout = self._tools.get_file(self._username, self._password, self._stdoutfile)
		if self._stderrfile:
			stderr = self._tools.get_file(self._username, self._password, self._stderrfile)
		return (stdout, stderr)

	def __str__(self):
		return repr(self)

	def __repr__(self):
		return f"<{type(self).__name__} for \"{self._command}\">"