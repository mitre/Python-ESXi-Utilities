from dateutil.parser import parse as parsetime
from esxi_utils.util.response import Response
from esxi_utils.util import log, exceptions
import subprocess
import datetime
import typing
import random
import ntpath
import winrm
import time
import re


class WinRMConnection:
	"""
	A WinRM connection to a Windows remote host.

	:param ip: The IP of the virtual machine.
	:param username: The username to use when logging into the virtual machine. If `domain` is not specified, this username should take the form `user@domain` (if a domain is available).
	:param password: The password to use when logging into the virtual machine.
	:param domain: The domain (if available) for the user.
	:param transport: Transport type for winrm connection. Defaults to NTLM.
	"""
	def __init__(self, ip: str, username: str, password: str, domain: typing.Optional[str] = None, transport: str = "ntlm"):
		if domain:
			username = f"{username}@{domain}"
		self._ip = ip
		self._username = username
		self._password = password
		self._transport = transport
		self._connection = None

	def __enter__(self) -> 'WinRMConnection':
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
		
		if self._transport == 'kerberos':
			log.debug('Using kinit to create kerberos ticket')
			try:
				p = subprocess.run(args=['kinit', self._username], input=f'{self._password}\n'.encode(), capture_output=True)
				log.debug(f'kinit stdout: {p.stdout}')
				log.debug(f'Kinit stderr: {p.stderr}')
				if p.returncode != 0:
					raise ChildProcessError(p.stderr.decode())
			except FileNotFoundError:
				raise FileNotFoundError('kinit command does not exist. Make sure to install all necessary kerberos packages')
		
		kwargs = dict()
		kwargs['transport'] = self._transport
		self._connection = winrm.Session(self._ip, auth=(self._username, self._password), **kwargs)

	def close(self):
		"""
		Terminate the network connection to the remote end, if open.

		If no connection is open, this method does nothing.
		"""
		self._connection = None

	def wait(self, retries: int = 10, delay: int = 5, keep_open=False) -> bool:
		"""
		Waits until this connection can be established, and then establishes the connection.

		:param retries: How many times to retry connecting before exiting. Authentication errors will terminate the wait early.
		:param delay: How long to pause between retries in seconds.
		:param keep_open: Whether or not the keep the connection open. If `True`, it is left to the user to close the connection.

		:return: Whether or not the connection could be established
		"""
		from winrm.exceptions import AuthenticationError, BasicAuthDisabledError, InvalidCredentialsError
		fault_tolerance = 2 # When a VM is booting, we may get false errors that resolve with time; allow this many hard failures before exiting
		for i in range(retries):
			log.debug(f"connection attempt {i}")
			if i != 0:
				time.sleep(delay)
			try:
				self.open()
				log.debug(f"open session")
				self.powershell("ls")
				return True
			except (AuthenticationError, BasicAuthDisabledError, InvalidCredentialsError) as e:
				if fault_tolerance == 0:
					raise e
				else:
					fault_tolerance -= 1
					time.sleep(random.randint(20, 40))
			except Exception:
				continue
			finally:
				if not keep_open:
					self.close()
		return False

	def _exec(self, cmd: str, cmdtype: str, assert_status: typing.Optional[int] = None) -> 'Response':
		"""
		Execute a command on the remote end of this connection.

		:param cmd: The command to run.
		:param cmdtype: The type of command to run (either 'powershell' or 'cmd')
		:param assert_status: Assert that the command exits with a certain status number. If `None`, no assertion is made and checking the status is left to the caller.

		:return: A `Response` object.
		"""
		if self._connection is None:
			raise exceptions.RemoteConnectionNotOpenError(self)
		log.info(f"{str(self)} Running '{cmdtype}' command: {cmd}")
		resp = None
		if cmdtype == "cmd":
			resp = self._connection.run_cmd(cmd)
		elif cmdtype == "powershell":
			resp = self._connection.run_ps(cmd)
		else:
			raise KeyError("Unknown command type: " + cmdtype)
		result = Response(cmd=cmd, stdout=resp.std_out.decode(), stderr=resp.std_err.decode(), status=resp.status_code)
		if assert_status is not None and assert_status != result.status:
			raise exceptions.RemoteConnectionCommandError(self, result)
		return result
		
	def powershell(self, cmd: str, assert_status: typing.Optional[int] = None) -> 'Response':
		"""
		Execute a powershell command on the remote end of this connection.

		:param cmd: The command to run.
		:param assert_status: Assert that the command exits with a certain status number. If `None`, no assertion is made and checking the status is left to the caller.

		:return: A `Response` object.
		"""
		return self._exec(cmd, cmdtype="powershell", assert_status=assert_status)
		
	def cmd(self, cmd: str, assert_status: typing.Optional[int] = None) -> 'Response':
		"""
		Execute a cmd command on the remote end of this connection.

		:param cmd: The command to run.
		:param assert_status: Assert that the command exits with a certain status number. If `None`, no assertion is made and checking the status is left to the caller.

		:return: A `Response` object.
		"""
		return self._exec(cmd, cmdtype="cmd", assert_status=assert_status)

	def isfile(self, path: str) -> bool:
		"""
		Checks if the file exists and is a regular file.

		:param path: A path to a file on the remote system.
		
		:return: A boolean whether or not the file exists.
		"""
		return self.powershell(f"(Get-Item \"{path}\") -is [System.IO.FileInfo]").stdout.lower().strip() == "true"

	def isdir(self, path: str) -> bool:
		"""
		Checks if the directory exists.

		:param path: A path to a directory on the remote system.
		
		:return: A boolean whether or not the directory exists.
		"""
		return self.powershell(f"(Get-Item \"{path}\") -is [System.IO.DirectoryInfo]").stdout.lower().strip() == "true"

	def touch(self, path: str):
		"""
		Create an empty file.

		:param path: Path to the new file on the remote system.
		"""
		self.powershell(f"New-Item -Path \"{path}\" -ItemType File", assert_status=0)

	def mkdir(self, path: str, parents: bool = False):
		"""
		Create a directory.

		:param path: Path to the new directory on the remote system.
		:param parents: Whether or not the create parent directories as needed.
		"""
		if not parents:
			# The New-Item command makes directories recursive, so if parents=False we need to check explicitly if the parent exists
			parentdir = ntpath.dirname(path)
			if not self.isdir(parentdir):
				raise exceptions.RemoteNotADirectoryError(self, parentdir)
		self.powershell(f"New-Item -Path \"{path}\" -ItemType Directory", assert_status=0)

	def directory_is_empty(self, path: str) -> bool:
		"""
		Checks whether or not the given directory is empty.

		:param path: Path to the directory on the remote system.

		:return: Boolean whether or not `path` is empty. If the directory does not exist, an error will be thrown.
		"""
		return self.powershell(f"(Get-ChildItem \"{path}\" -Force | Select-Object -First 1 | Measure-Object).Count -eq 0", assert_status=0).stdout.lower().strip() == "true"

	def rm(self, path: str, recursive: bool = False):
		"""
		Remove a file or directory.

		:param path: Path to the directory to remove on the remote system.
		:param recursive: Whether or not the delete directories recursively (required to be True for removing directories).
		"""
		if not recursive and self.isdir(path) and not self.directory_is_empty(path):
			# This check is necessary since trying to remove a non-empty directory without the recurse parameter will cause this command to hang
			raise exceptions.RemoteConnectionError(self, f"Failed to remove {path} as the directory is not empty (use recursive=True)")
		self.powershell(f"Remove-Item -Path \"{path}\" -Force" + (" -Recurse" if recursive else ""), assert_status=0)

	def cp(self, src: str, dst: str, recursive: bool = False):
		"""
		Copy a file or directory.

		:param src: The source for the `cp` command. File globs may be used.
		:param dst: The destination for the `cp` command. If the destination exists, it will be overwritten.
		:param recursive: Copy directories and their contents recursively (required to be True for copying directories).
		"""
		self.powershell(f"Copy-Item -Path \"{src}\" -Destination \"{dst}\" -Force" + (" -Recurse" if recursive else ""), assert_status=0)

	def mv(self, src: str, dst: str):
		"""
		Move a file or directory.

		:param src: The source for the `mv` command. File globs may be used.
		:param dst: The destination for the `mv` command. If the destination exists, it will be overwritten.
		"""
		self.powershell(f"Move-Item -Path \"{src}\" -Destination \"{dst}\" -Force", assert_status=0)

	def ls(self, path: str) -> typing.List[str]:
		"""
		List the files within a directory.

		:param path: Path to the directory on the remote system.

		:return: A list of files in the directory
		"""
		return re.split("\n|\r\n", str(self.powershell(f"(Get-ChildItem -Path \"{path}\" -Force -ErrorAction stop).Name", assert_status=0).stdout))

	def list_installed_packages(self) -> typing.List[str]:
		"""
		Returns a list of installed packages on the VM.

		:return: A list of strings.
		"""
		return re.split("\n|\r\n", str(self.powershell(f"(Get-WmiObject -Class Win32_Product).Name", assert_status=0).stdout))

	def uninstall_package(self, name: str):
		"""
		Uninstall a package by name on the VM.

		:param name: The exact name of the package to uninstall (refer to `list_installed_packages`).
		"""
		self.powershell(f"(Get-WmiObject -Class Win32_Product -Filter \"Name='{name}'\").Uninstall()", assert_status=0)

	def restart(self):
		"""
		Perform a graceful restart of the VM using `Restart-Computer -Force`. This will close the current connection.
		"""
		self.powershell("Restart-Computer -Force")
		self.close()

	def shutdown(self):
		"""
		Attempt a graceful shutdown of the VM using `Stop-Computer -Force`. This will close the current connection.
		"""
		self.powershell("Stop-Computer -Force")
		self.close()

	def time(self):
		"""
		Get the current time set on the remote host.

		:return: A `datetime` object.
		"""
		resp = self.powershell(r"Get-Date -UFormat '%A, %B %d %Y, %R:%S %Z00'", assert_status=0)
		return parsetime(resp.stdout.splitlines()[-1].strip()).astimezone(datetime.timezone.utc)

	@staticmethod
	def parse_PS_objects(str):
		obj_strings = str.split('\r\n\r\n')
		key = None
		value = None
		objs = []
		for obj_string in obj_strings:
			obj = {}
			for line in obj_string.splitlines():
				if ' : ' in line:
					# We have a new key value
					key, value = [s.strip() for s in line.split(' : ', 2)]
					obj[key] = value
				elif key:
					# If we get to a new line, we append the value to the last key
					obj[key] = obj[key]+line.strip()
			objs.append(obj)
		return objs

	def get_AD_group(self, name: str) -> typing.Dict[str, typing.Any]:
		"""
		Retrieves AD group information with group members.

		:param name: The name of the Active Directory group.

		:return: An dict containing information about the Active Directory group.
		"""
		resp = self.powershell(f"Get-ADgroup -Identity {name}", assert_status=0)
		group_data = self.parse_PS_objects(resp.stdout)[0]

		return_obj = dict()
		return_obj['name'] = group_data['Name']
		return_obj['distinguished_name'] = [s.strip() for s in group_data['DistinguishedName'].split(',')]
		return_obj['group_category'] = group_data['GroupCategory']
		return_obj['group_scope'] = group_data['GroupScope']

		resp = self.powershell(f"Get-ADGroupMember -Identity {name}", assert_status=0)
		member_data = self.parse_PS_objects(resp.stdout)

		return_obj['members'] = [ { 'name': memb['name'], 'object_class': memb['objectClass'] } for memb in member_data ]
		return return_obj
		
	def __str__(self):
		return f"<{type(self).__name__} {self._username} at {self._ip}>"

	def __repr__(self):
		return str(self)
		