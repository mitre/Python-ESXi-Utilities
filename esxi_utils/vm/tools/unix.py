from esxi_utils.vm.tools.guesttools import GuestTools, GuestToolsResponsePromise
from esxi_utils.util.response import Response
from esxi_utils.util import log, exceptions
import typing
import stat
import os
import re

class UnixGuestTools(GuestTools):
	"""
	Guest tools subclass specifically for interaction with a Unix or Unix-like operating system

	Wrapper class for functionality related to VMware Tools on a Virtual Machine. The virtual machine must have VMware tools installed for
	any of the contained functions to work.

	:param vm: A `VirtualMachine` object to wrap. VMware tools must be installed on this virtual machine.
	"""
	def bash_async(
		self, 
		username: str,
		password: str, 
		command: str, 
		cwd: typing.Optional[str] = None,
		bash_path: str = "/bin/bash",
		sudo: typing.Union[bool, str] = False,
		out_stream_callback: typing.Optional[typing.Callable[[str], None]] = None
	) -> 'GuestToolsBashResponsePromise':
		"""
		Runs a script in the guest operating system asynchronously using bash.

		Unlike ``execute_program``, the command is executed as a standard bash script and thus the full path to programs do not need to be provided. 
		Systems without bash will fail. ``command`` may also be provided as a script, with newlines separating the commands to be run.

		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.
		:param command: The command or script to run.
		:param cwd: The working directory that the command should be run in.
		:param bash_path: The path to the bash executable.
		:param sudo: Whether to run the command with sudo. If `True`, the `password` parameter will be passed to sudo. Provide a string to use a different password for sudo.
		:param out_stream_callback: Optional callback to handle the stdout of commands. If not `None`, this will be called as a command's stdout becomes available. 
	
		:return: A `GuestToolsBashResponsePromise` object
		"""
		return GuestToolsBashResponsePromise(
			tools=self, 
			username=username, 
			password=password, 
			command=command, 
			cwd=cwd,
			bash_path=bash_path, 
			sudo=sudo,
			out_stream_callback=out_stream_callback
		)

	def bash(
		self, 
		username: str,
		password: str, 
		command: str, 
		cwd: typing.Optional[str] = None,
		bash_path: str = "/bin/bash",
		sudo: typing.Union[bool, str] = False,
		timeout: typing.Optional[int] = 120,
		assert_status: typing.Optional[int] = None,
		out_stream_callback: typing.Optional[typing.Callable[[str], None]] = None
	) -> 'Response':
		"""
		Runs a script in the guest operating system using bash. Unlike ``bash_async``, this will block until the associated command has finished.

		Unlike ``execute_program``, the command is executed as a standard bash script and thus the full path to programs do not need to be provided. 
		Systems without bash will fail. ``command`` may also be provided as a script, with newlines separating the commands to be run.

		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.
		:param command: The command or script to run.
		:param cwd: The working directory that the command should be run in.
		:param bash_path: The path to the bash executable.
		:param sudo: Whether to run the command with sudo. If `True`, the `password` parameter will be passed to sudo. Provide a string to use a different password for sudo.
		:param timeout: The command timeout in seconds. Set to 0 or `None` to disable timeout.
		:param assert_status: Assert that the command exits with a certain status number. If `None`, no assertion is made and checking the status is left to the caller.
		:param out_stream_callback: Optional callback to handle the stdout of commands. If not `None`, this will be called as a command's stdout becomes available. 

		:return: A `Response` object
		"""
		return self.bash_async(
			username=username, 
			password=password, 
			command=command, 
			cwd=cwd,
			bash_path=bash_path, 
			sudo=sudo,
			out_stream_callback=out_stream_callback
		).wait(assert_status=assert_status, timeout=timeout)

	def stat(self, path: str, username: str, password: str, bash_path: str = "/bin/bash", sudo: typing.Union[bool, str] = False) -> typing.Union[typing.Dict[str, typing.Any], None]:
		"""
		Get information about a file.

		:param path: A path to a file or directory on the remote system.
		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.
		:param bash_path: The path to the bash executable.
		:param sudo: Whether to run commands with sudo. If `True`, the `password` parameter will be passed to sudo. Provide a string to use a different password for sudo.

		:return: A dict containing information about the file, or `None` if the file does not exist.
		"""
		log.debug(f"{str(self)} Stat {path}")
		response = self.bash(
			username=username,
			password=password,
			command=f"stat -c '%s %f %Y %X %g %u' '{path}'",
			bash_path=bash_path,
			sudo=sudo
		)
		output = str(response.stdout) + "\n" + str(response.stderr)
		output = output.strip()
		if response.status != 0 and f"no such file" in output.lower():
			return None
		elif response.status != 0:
			raise exceptions.RemoteConnectionCommandError(self, response)
		
		split = output.split(" ")
		size = int(split[0])
		mode = int(split[1], 16)
		mtime = int(split[2])
		atime = int(split[3])
		gid = int(split[4])
		uid = int(split[5])

		return {
			"name": os.path.basename(path),
			"size": size,
			"mode": mode,
			"isfile": stat.S_ISREG(mode),
			"isdir": stat.S_ISDIR(mode),
			"mtime": mtime,
			"atime": atime,
			"gid": gid,
			"uid": uid
		}

	def bulkstat(self, paths: typing.List[str], username: str, password: str, bash_path: str = "/bin/bash", sudo: typing.Union[bool, str] = False) -> typing.List[typing.Dict[str, typing.Any]]:
		"""
		Get information about one or more files.

		:param paths: The paths to the files or directories on the remote system.
		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.
		:param bash_path: The path to the bash executable.
		:param sudo: Whether to run commands with sudo. If `True`, the `password` parameter will be passed to sudo. Provide a string to use a different password for sudo.

		:return: A dict containing information about the file, or `None` if the file does not exist.
		"""
		paths_string = " ".join([ f"'{path}'" for path in paths ])
		log.debug(f"{str(self)} Bulk Stat: {', '.join(paths)}")

		with self.use_temporary_file(username=username, password=password, extension=".stat") as output_file:
			self.bash(
				username=username,
				password=password,
				command=f"stat -c '%s %f %Y %X %g %u' {paths_string} > {output_file} 2>&1",
				bash_path=bash_path,
				sudo=sudo
			)

			output: str = self.get_file(username=username, password=password, filepath=output_file) # type: ignore

		lines = output.strip().split("\n")
		if len(lines) != len(paths):
			raise RuntimeError(f"bulkstat: the number of output lines do not match the number of input files")

		stats = list()
		for path, line in zip(paths, lines):
			obj = {
				"path": path,
				"name": os.path.basename(path),
				"exists": True,
				"size": None,
				"mode": None,
				"isfile": None,
				"isdir": None,
				"mtime": None,
				"atime": None,
				"gid": None,
				"uid": None
			}

			if f"no such file" in line.lower():
				obj["exists"] = False
				stats.append(obj)
				continue

			try:
				split = line.split(" ")
				obj["size"] = int(split[0])
				obj["mode"] = int(split[1], 16)
				obj["isfile"] = stat.S_ISREG(obj["mode"])
				obj["isdir"] = stat.S_ISDIR(obj["mode"])
				obj["mtime"] = int(split[2])
				obj["atime"] = int(split[3])
				obj["gid"] = int(split[4])
				obj["uid"] = int(split[5])
				stats.append(obj)
			except Exception:
				raise RuntimeError(f"Failed to stat file {path}: {line}")
		return stats
	
	def isfile(self, path: str, username: str, password: str, bash_path: str = "/bin/bash", sudo: typing.Union[bool, str] = False) -> bool:
		"""
		Checks if the file exists and is a regular file.

		:param path: A path to a file on the remote system.
		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.
		:param bash_path: The path to the bash executable.
		:param sudo: Whether to run commands with sudo. If `True`, the `password` parameter will be passed to sudo. Provide a string to use a different password for sudo.
		
		:return: A boolean whether or not the file exists.
		"""
		stat = self.stat(
			path, 
			username=username, 
			password=password,
			bash_path=bash_path,
			sudo=sudo
		)
		if stat is None:
			return False
		return stat["isfile"]

	def isdir(self, path: str, username: str, password: str, bash_path: str = "/bin/bash", sudo: typing.Union[bool, str] = False) -> bool:
		"""
		Checks if the directory exists.

		:param path: A path to a directory on the remote system.
		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.
		:param bash_path: The path to the bash executable.
		:param sudo: Whether to run commands with sudo. If `True`, the `password` parameter will be passed to sudo. Provide a string to use a different password for sudo.
		
		:return: A boolean whether or not the directory exists.
		"""
		stat = self.stat(
			path, 
			username=username, 
			password=password,
			bash_path=bash_path,
			sudo=sudo
		)
		if stat is None:
			return False
		return stat["isdir"]

	def download(
		self, 
		path: str, 
		dst: str, 
		username: str,
		password: str,
		directory_contents_only: bool = False, 
		overwrite: bool = False,
		bash_path: str = "/bin/bash",
	) -> typing.List[str]:
		"""
		Download a file or directory from the remote system.

		:param path: Path to the file or directory on the remote system.
		:param dst: The local destination file or directory to download to.
		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.
		:param directory_contents_only: If `True` and `path` points to a directory, then just the contents of the directory will be downloaded rather than the directory itself.
		:param overwrite: Whether to overwrite existing files.
		:param bash_path: The path to the bash executable.

		:return: A list of local paths to all files downloaded.
		"""
		log.info(f"{str(self)} Downloading \"{path}\" to \"{dst}\"...")
		dst = os.path.abspath(dst)
		basename = os.path.basename(path)
		stat = self.stat(path, username=username, password=password, bash_path=bash_path)
		if stat is None:
			raise exceptions.RemoteFileNotFoundError(self, path)

		download_map: typing.Dict[str, str] = {} # Map download source -> destination
		if stat["isfile"]:
			# Single file download
			target = dst
			if not os.path.exists(target):
				# Target doesn't exist, we will download under the name specified
				# Just ensure the parent directory does exist
				parent = os.path.dirname(target)
				if not os.path.isdir(parent):
					raise NotADirectoryError(f"{parent} is not a valid local directory")
			else:
				# Target exists, we'll download into the target with the same name
				if not os.path.isdir(target):
					raise NotADirectoryError(f"{target} is not a valid local directory")
				target = os.path.join(target, basename)
			download_map[path] = target
		else:
			# Directory download
			target = dst
			if os.path.isdir(target) and directory_contents_only:
				# Downloading directory contents into a directory
				pass
			elif os.path.isdir(target) and not directory_contents_only:
				# Downloading directory into a directory, download with the same name into the target
				target = os.path.join(target, stat["name"])
			elif not os.path.exists(target) and directory_contents_only:
				# We cannot download the contents of a directory if the dst does not exist
				raise NotADirectoryError(f"{dst} is not a valid local directory")
			elif not os.path.exists(target) and not directory_contents_only:
				# Downloading directory under a new name, we just need to ensure that the parent directory exists
				parent = os.path.dirname(target)
				if not os.path.isdir(parent):
					raise NotADirectoryError(f"{parent} is not a valid local directory")
			
			download_map = {}
			files_to_download = [ os.path.join(path, filename) for filename in self.list_files(username=username, password=password, filepath=path) ]
			while len(files_to_download):
				stats = self.bulkstat(files_to_download, username=username, password=password, bash_path=bash_path)
				files_to_download = []
				for stat in stats:
					if stat["isdir"]:
						files_to_download.extend([ os.path.join(stat["path"], filename) for filename in self.list_files(username=username, password=password, filepath=stat["path"]) ])
						continue
					download_map[stat["path"]] = os.path.join(target, stat["path"][len(path):].strip("/"))

		if len(download_map.keys()) == 0:
			return []

		for target in download_map.values():
			if os.path.exists(target) and not overwrite:
				raise FileExistsError(f"{target} already exists")
			if os.path.isdir(target):
				raise IsADirectoryError(f"{target} cannot be overwritten as it exists as a directory")

		# Begin downloading files
		for remotepath, localpath in download_map.items():
			log.debug(f"{self} Downloading {remotepath} to {localpath}")
			os.makedirs(os.path.dirname(localpath), exist_ok=True)
			file_bytes: bytes = self.get_file(username=username, password=password, filepath=remotepath, encoding=None) # type: ignore
			with open(localpath, mode="wb") as f:
				f.write(file_bytes)

		return list(download_map.values())

	def upload(
		self, 
		src: str,
		dst: str,
		username: str,
		password: str,
		directory_contents_only: bool = False, 
		overwrite: bool = False,
		bash_path: str = "/bin/bash",
	) -> typing.List[str]:
		"""
		Upload a local file or directory to this path on the remote system.
		
		Warning: This function will load entire files into memory. Ensure that extremely large files are not uploaded using this method.

		:param src: The local path to a file or directory to upload.
		:param dst: The remote path to upload to.
		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.
		:param directory_contents_only: If `True` and `src` points to a directory, then only the contents of the directory will be uploaded rather than the directory itself.
		:param overwrite: Whether to overwrite existing files on the remote system.
		:param bash_path: The path to the bash executable.

		:return: A list of remote paths to all files uploaded.
		"""
		log.info(f"<{self}> Uploading \"{src}\" to \"{dst}\"...")
		src = os.path.abspath(src)
		if not os.path.exists(src):
			raise FileNotFoundError(f"File or directory {src} not found")

		dst_stat = self.stat(dst, username=username, password=password, bash_path=bash_path)

		upload_map: typing.Dict[str, str] = {} # Map upload source -> destination
		if os.path.isfile(src):
			# Single file upload
			target = dst
			if dst_stat is None:
				# Target doesn't exist, we will upload under the name specified
				# Just ensure the parent directory does exist
				parent = os.path.dirname(target)
				if not self.isdir(parent, username=username, password=password, bash_path=bash_path):
					raise exceptions.RemoteNotADirectoryError(self, parent)
			else:
				# Target exists, we'll upload into the target with the same name
				if not dst_stat["isdir"]:
					raise exceptions.RemoteNotADirectoryError(self, dst)
				target = os.path.join(target, os.path.basename(src))
			upload_map[src] = target
		elif os.path.isdir(src):
			# Directory upload
			target = dst
			target_exists = dst_stat is not None
			target_is_dir = dst_stat and dst_stat["isdir"]
			if target_is_dir and directory_contents_only:
				# Uploading directory contents into a directory
				pass
			elif target_is_dir and not directory_contents_only:
				# Uploading directory into a directory, upload with the same name into the target
				target = os.path.join(target, os.path.basename(src))
			elif not target_exists and directory_contents_only:
				# We cannot upload the contents of a directory if the dst does not exist
				raise exceptions.RemoteNotADirectoryError(self, target)
			elif not target_exists and not directory_contents_only:
				# Uploading directory under a new name, we just need to ensure that the parent directory exists
				parent = os.path.dirname(target)
				if not self.isdir(parent, username=username, password=password, bash_path=bash_path):
					raise exceptions.RemoteNotADirectoryError(self, parent)
			
			for root, _, files in os.walk(src):
				for file in files:
					path = os.path.join(root, file)
					upload_map[path] = os.path.join(target, path[len(src):].strip("/"))

		if len(upload_map.keys()) == 0:
			return []

		for stat in self.bulkstat(list(upload_map.values()), username=username, password=password):
			if stat["exists"] and stat["isfile"] and not overwrite:
				raise exceptions.RemoteFileExistsError(self, stat["path"])
			if stat["exists"] and stat["isdir"]:
				raise exceptions.RemoteIsADirectoryError(self, stat["path"])

		# Determine the directories to create
		# We will be running mkdir with parents, so we only want the longest paths
		dirs_to_make = []
		for remotepath in upload_map.values():
			dirname = os.path.dirname(remotepath).rstrip("/") + "/"
			dirs_to_make = [ path for path in dirs_to_make if not dirname.startswith(path) ] # Remove any paths that are subsets of this path 
			is_subpath = any([ path.startswith(dirname) for path in dirs_to_make ]) # Check if this is a subpath of any existing path already
			if not is_subpath:
				dirs_to_make.append(dirname)
		
		# Make directories
		mkdir_path_string = " ".join([ f"'{path}'" for path in dirs_to_make ])
		self.bash(
			username=username, 
			password=password,
			command=f"mkdir -p {mkdir_path_string}",
			bash_path=bash_path,
			assert_status=0
		)

		# Begin uploading files
		for localpath, remotepath in upload_map.items():
			log.debug(f"<{self}> Uploading \"{localpath}\" to \"{remotepath}\"")
			with open(localpath, "rb") as f:
				self.write_file(username=username, password=password, filepath=remotepath, data=f.read())

		return list(upload_map.values())
	

class GuestToolsBashResponsePromise(GuestToolsResponsePromise):
	"""
	Encapsulates a Promise for a result of an GuestTools Bash command.

	:param tools: The UnixGuestTools instance from which this promise originates.
	:param username: The username of the virtual machine user.
	:param password: The password of the virtual machine user.
	:param command: The command or script to run.
	:param bash_path: The path to the bash executable.
	:param sudo: Whether to run the command with sudo. If `True`, the `password` parameter will be passed to sudo. Provide a string to use a different password for sudo.
	:param out_stream_callback: Optional callback to handle the stdout of commands. If not `None`, this will be called as a command's stdout becomes available. 
	"""
	def __init__(
		self, 
		tools: UnixGuestTools, 
		username: str, 
		password: str, 
		command: str, 
		cwd: typing.Optional[str] = None, 
		bash_path: str = "/bin/bash", 
		sudo: typing.Union[bool, str] = False,
		out_stream_callback: typing.Optional[typing.Callable[[str], None]] = None
	):
		assert isinstance(cwd, str) or cwd is None, "cwd must be a string or None"
		assert isinstance(bash_path, str), "bash_path must be a string"
		assert isinstance(sudo, (str, bool)), "sudo must be a string or boolean"

		self._bash_path = bash_path
		self._sudo = sudo
		self._scriptfile = None
		
		super().__init__(
			tools=tools, 
			username=username, 
			password=password, 
			command=command,
			cwd=None,
			make_output_available=True,
			out_stream_callback=out_stream_callback
		)

	def _setup(self, make_output_available: bool = False) -> str:
		"""
		Perform any setup necessary prior to starting the command.

		:param make_output_available: Whether or not it is requested to make the output of the command available.
		
		:return: The command to run.
		"""
		self._scriptfile = self._tools.create_temporary_file(self._username, self._password, ".sh")
		self._tools.write_file(username=self._username, password=self._password, filepath=self._scriptfile, data=f"cd {self._cwd}\n{self._command}" if self._cwd else self._command)

		command = f"{self._bash_path} -eu {self._scriptfile}"

		# Handle sudo
		if self._sudo:
			# As root; invoke the script with sudo
			sudo_password = self._sudo if isinstance(self._sudo, str) else self._password
			command = f"{self._bash_path} -c \"echo '{sudo_password}' | sudo -S {command}\""

		# Handle stdout/stderr
		if make_output_available:
			self._stdoutfile = self._tools.create_temporary_file(self._username, self._password, ".out")
			self._stderrfile = self._tools.create_temporary_file(self._username, self._password, ".err")
			command = f"{command} > {self._stdoutfile} 2> {self._stderrfile}"

		return command

	def _format_response(self, response: Response) -> Response:
		"""
		Perform post-processing on a result. This will occur when a command finishes executing but before any files are cleaned up.

		:param response: The result of the command.

		:return: The new result.
		"""
		if self._sudo:
			response.stdout = re.sub(r"^\[sudo\] password[^\n]+\n?", "", str(response.stdout))
			response.stderr = re.sub(r"^\[sudo\] password[^\n]+\n?", "", str(response.stderr))
		return response
	
	def _cleanup(self):
		"""
		Clean up any files or other resources after the process has finished.
		"""
		super()._cleanup()
		if self._scriptfile:
			self._tools.delete_file(self._username, self._password, self._scriptfile)
			self._scriptfile = None
