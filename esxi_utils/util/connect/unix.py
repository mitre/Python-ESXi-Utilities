from esxi_utils.util.connect.ssh import SSHConnection, SSHResponsePromise
from dateutil.parser import parse as parsetime
from esxi_utils.util import log, exceptions
import datetime
import typing
import uuid
import stat
import os
import re

if typing.TYPE_CHECKING:
	from esxi_utils.util.response import Response

class UnixSSHConnection(SSHConnection):
	"""
	A SSH connection to a Unix or Unix-like remote host.

	:param ip: The IP of the target.
	:param username: The username to use when logging into the remote system.
	:param password: The password to use when logging into the remote system.
	:param sudo_password: The password to use when running as sudo. Only necessary if the sudo password differs from `password`, as `password` will be used as the default.
	:param port: The port to use when connecting over SSH.
	:param min_pty_width: The minimum width of pseudoterminals (in columns) when ``pty=True`` is set on a command.
	:param min_pty_height: The minimum height of pseudoterminals (in rows) when ``pty=True`` is set on a command.
	"""
	def __init__(self, ip: str, username: str, password: str, sudo_password: typing.Optional[str] = None, port: int = 22, min_pty_width: int = 160, min_pty_height: int = 48):
		super().__init__(
			ip=ip, 
			username=username,
			password=password,
			port=port,
			min_pty_width=min_pty_width,
			min_pty_height=min_pty_height,
		)
		self._sudo_password = sudo_password

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
		sudo_password: typing.Optional[str] = None,
	) -> 'Response':
		"""
		Execute a shell command on the remote end of this connection. Includes some Unix-specific functionality, such as handling sudo prompts (hint: use `sudo {cmd}` to run a command as root).

		:param cmd: The command to run.
		:param stdin: A dict mapping a 'pattern' (regex string) to a 'response' (string), to input 'response' to stdin when stdout matches 'pattern'
		:param timeout: The command timeout in seconds. Set to 0 to disable timeout.
		:param pty: Run the command in a pseudoterminal. If `True`, the returned `Response` object will have a merged stdout and stderr, and stderr will be empty.
		:param cwd: The directory that the command should run in. If `None`, runs in the default directory.
		:param env: A dict of shell environment variables to be merged into the default environment that the remote command executes within.
		:param out_stream_callback: Optional callback to handle the stdout of commands. If not `None`, this will be called as a command's stdout becomes available. 
		:param assert_status: Assert that the command exits with a certain status number. If `None`, no assertion is made and checking the status is left to the caller.
		:param network_retries: Number of times to retry the command when a recoverable network error is encountered. The command should be idempotent when this is non-zero as it may run several times.
		:param sudo_password: The password to use for sudo prompts. If not provided, this will default first to the `sudo_password` on the SSH connection object, and then to the `password` on the SSH connection object.
		
		:return: A `Response` object.
		"""
		if not isinstance(stdin, dict):
			stdin = dict()
		stdin = { key: value for key, value in stdin.items() } # Create a copy
		sudo_pass = self._password
		if sudo_password:
			sudo_pass = sudo_password
		elif self._sudo_password:
			sudo_pass = self._sudo_password
		stdin[r"\[sudo\] password"] = sudo_pass + "\n"
		return SSHConnection.exec(
			self,
			cmd=cmd,
			stdin=stdin,
			timeout=timeout,
			pty=pty,
			cwd=cwd,
			env=env,
			out_stream_callback=out_stream_callback,
			assert_status=assert_status,
			network_retries=network_retries
		)
	
	def exec_script(
		self, 
		script: str, 
		stdin: typing.Optional[typing.Dict[str, str]] = None, 
		timeout: int = 120, 
		pty: bool = False, 
		cwd: typing.Optional[str] = None, 
		env: typing.Optional[typing.Dict[str, typing.Any]] = None, 
		out_stream_callback: typing.Optional[typing.Callable[[str], None]] = None,
		assert_status: typing.Optional[int] = None,
		network_retries: int = 0,
		use_sudo: bool = False,
		sudo_password: typing.Optional[str] = None,
	) -> 'Response':
		"""
		Execute a script on the remote end of this connection. This will write a temporary script file and execute it on the remote end of this connection.

		:param script: The script to run.
		:param stdin: A dict mapping a 'pattern' (regex string) to a 'response' (string), to input 'response' to stdin when stdout matches 'pattern'
		:param timeout: The command timeout in seconds. Set to 0 to disable timeout.
		:param pty: Run the command in a pseudoterminal. If `True`, the returned `Response` object will have a merged stdout and stderr, and stderr will be empty.
		:param cwd: The directory that the command should run in. If `None`, runs in the default directory.
		:param env: A dict of shell environment variables to be merged into the default environment that the remote command executes within.
		:param out_stream_callback: Optional callback to handle the stdout of commands. If not `None`, this will be called as a command's stdout becomes available. 
		:param assert_status: Assert that the command exits with a certain status number. If `None`, no assertion is made and checking the status is left to the caller.
		:param network_retries: Number of times to retry the command when a recoverable network error is encountered. The script should be idempotent when this is non-zero as it may run several times.
		:param use_sudo: Whether to run the entire script using sudo. Setting this to `False` does not forgo the possibility of using sudo commands within the script itself.
		:param sudo_password: The password to use for sudo prompts. If not provided, this will default first to the `sudo_password` on the SSH connection object, and then to the `password` on the SSH connection object.
		
		:return: A `Response` object.
		"""
		script = re.sub(r"^\s*", "", script, flags=re.MULTILINE).strip()
		script_path = f"/tmp/{str(uuid.uuid4()).replace('-', '')}.sh"
		self.write(script_path, script)
		
		script_cmd = f"bash -eu {script_path}"
		if use_sudo:
			script_cmd = "sudo " + script_cmd
		try:
			resp = self.exec(
				cmd=script_cmd,
				stdin=stdin,
				timeout=timeout,
				pty=pty,
				cwd=cwd,
				env=env,
				out_stream_callback=out_stream_callback,
				assert_status=assert_status,
				network_retries=network_retries,
				sudo_password=sudo_password
			)
			resp.cmd = script
			return resp
		finally:
			self.rm(script_path)

	def exec_async(
		self, 
		cmd: str, 
		stdin: typing.Optional[typing.Dict[str, str]] = None, 
		timeout: int = 120, 
		pty: bool = False,
		cwd: typing.Optional[str] = None, 
		env: typing.Optional[typing.Dict[str, typing.Any]] = None, 
		out_stream_callback: typing.Optional[typing.Callable[[str], None]] = None
	) -> 'SSHResponsePromise':
		"""
		Execute a shell command asynchronously on the remote end of this connection. Includes some Unix-specific functionality, such as handling sudo prompts (hint: use `sudo {cmd}` to run a command as root).

		:param cmd: The command to run.
		:param stdin: A dict mapping a 'pattern' (regex string) to a 'response' (string), to input 'response' to stdin when stdout matches 'pattern'
		:param timeout: The command timeout in seconds. Set to 0 to disable timeout.
		:param pty: Run the command in a pseudoterminal. If `True`, the returned `Response` object will have a merged stdout and stderr, and stderr will be empty.
		:param cwd: The directory that the command should run in. If `None`, runs in the default directory.
		:param env: A dict of shell environment variables to be merged into the default environment that the remote command executes within.
		:param out_stream_callback: Optional callback to handle the stdout of commands. If not `None`, this will be called as a command's stdout becomes available. 

		:return: A `SSHResponsePromise` object.
		"""
		if not isinstance(stdin, dict):
			stdin = dict()
		stdin = { key: value for key, value in stdin.items() } # Create a copy
		sudo_pass = self._password
		if self._sudo_password:
			sudo_pass = self._sudo_password
		stdin[r"\[sudo\] password"] = sudo_pass + "\n"
		return SSHConnection.exec_async(
			self,
			cmd=cmd,
			stdin=stdin,
			timeout=timeout,
			pty=pty,
			cwd=cwd,
			env=env,
			out_stream_callback=out_stream_callback
		)

	def stat(self, path: str, cwd: typing.Optional[str] = None) -> typing.Union[typing.Dict[str, typing.Any], None]:
		"""
		Get information about a file.

		:param path: A path to a file or directory on the remote system.
		:param cwd: The current working directory. If `None`, no current working directory is used.
		
		:return: A dict containing information about the file, or `None` if the file does not exist.
		"""
		log.debug(f"{str(self)} Stat {path}")
		assert self._connection and self._connection.client, "Connection is not open"
		with self._connection.client.open_sftp() as ftp:
			ftp.chdir(cwd)
			try:
				s = ftp.stat(path)
			except FileNotFoundError:
				return None
			return {
				"name": os.path.basename(path),
				"size": s.st_size,
				"mode": s.st_mode,
				"isfile": stat.S_ISREG(s.st_mode), # type: ignore
				"isdir": stat.S_ISDIR(s.st_mode), # type: ignore
				"mtime": s.st_mtime,
				"atime": s.st_atime,
				"gid": s.st_gid,
				"uid": s.st_uid
			}

	def isfile(self, path: str, cwd: typing.Optional[str] = None) -> bool:
		"""
		Checks if the file exists and is a regular file.

		:param path: A path to a file on the remote system.
		:param cwd: The current working directory. If `None`, no current working directory is used.
		
		:return: A boolean whether or not the file exists.
		"""
		stat = self.stat(path, cwd=cwd)
		if stat is None:
			return False
		return stat["isfile"]

	def isdir(self, path: str, cwd: typing.Optional[str] = None) -> bool:
		"""
		Checks if the directory exists.

		:param path: A path to a directory on the remote system.
		:param cwd: The current working directory. If `None`, no current working directory is used.
		
		:return: A boolean whether or not the directory exists.
		"""
		stat = self.stat(path, cwd=cwd)
		if stat is None:
			return False
		return stat["isdir"]

	def touch(self, path: str, cwd: typing.Optional[str] = None):
		"""
		Create an empty file.

		:param path: Path to the new file on the remote system.
		:param cwd: The current working directory. If `None`, no current working directory is used.
		"""
		self.exec(f"touch {path}", assert_status=0, cwd=cwd)

	def mkdir(self, path: str, parents: bool = False, cwd: typing.Optional[str] = None):
		"""
		Create a directory.

		:param path: Path to the new directory on the remote system.
		:param parents: Whether or not the create parent directories as needed.
		:param cwd: The current working directory. If `None`, no current working directory is used.
		"""
		self.exec(f"mkdir -p {path}" if parents else f"mkdir {path}", assert_status=0, cwd=cwd)
	
	def rm(self, path: str, recursive: bool = False, cwd: typing.Optional[str] = None):
		"""
		Remove a file or directory.

		:param path: Path to the directory to remove on the remote system.
		:param recursive: Whether or not the delete directories recursively (required to be True for removing directories).
		:param cwd: The current working directory. If `None`, no current working directory is used.
		"""
		self.exec(f"rm -rf {path}" if recursive else f"rm -f {path}", assert_status=0, cwd=cwd)

	def cp(self, src: str, dst: str, recursive: bool = False, cwd: typing.Optional[str] = None):
		"""
		Copy a file or directory.

		:param src: The source for the `cp` command. File globs may be used.
		:param dst: The destination for the `cp` command. If the destination exists, it will be overwritten.
		:param recursive: Copy directories and their contents recursively (required to be True for copying directories).
		:param cwd: The current working directory. If `None`, no current working directory is used.
		"""
		self.exec(f"cp -r {src} {dst}" if recursive else f"cp {src} {dst}", assert_status=0, cwd=cwd)

	def mv(self, src: str, dst: str, cwd: typing.Optional[str] = None):
		"""
		Move a file or directory.

		:param src: The source for the `mv` command. File globs may be used.
		:param dst: The destination for the `mv` command. If the destination exists, it will be overwritten.
		:param cwd: The current working directory. If `None`, no current working directory is used.
		"""
		self.exec(f"mv -f {src} {dst}", assert_status=0, cwd=cwd)

	def ls(self, path: str, cwd: typing.Optional[str] = None, sudo_dash_S: bool=False, sudo_password: typing.Optional[str] = None):
		"""
		List the files within a directory using SFTP.

		:param path: Path to the directory on the remote system.
		:param cwd: The current working directory. If `None`, no current working directory is used.
		:param sudo_dash_S: when 'True' use exec the command: 'sudo -S ls -a' instead of using ftp.listdir() (cwd will be ignored)
		:param sudo_password: The password to use for sudo prompts. If not provided, this will default first to the `sudo_password` on the SSH connection object, and then to the `password` on the SSH connection object. This parameter is only used when sudo_dash_S is provided.
		"""
		assert self._connection and self._connection.client, "Connection is not open"
		if sudo_dash_S:
			return self.exec(f'sudo -S ls -a {path}', sudo_password=sudo_password).stdout.split('\n')
		with self._connection.client.open_sftp() as ftp:
			ftp.chdir(cwd)
			return ftp.listdir(path)

	def read(self, path: str, encoding: typing.Optional[str] = 'utf-8', cwd: typing.Optional[str] = None, sudo_dash_S: bool=False, sudo_password: typing.Optional[str] = None) -> typing.Union[str, bytes]:
		"""
		Read the contents of a file using SFTP.

		:param path: Path to the file on the remote system.
		:param encoding: The encoding to use when decoding the file to string. If `None`, no decoding is performed and bytes will be returned.
		:param cwd: The current working directory. If `None`, no current working directory is used.
		:param sudo_dash_S: when 'True' use exec the command: 'sudo -S cat' instead of using ftp.file.read() (cwd will be ignored)
		:param sudo_password: The password to use for sudo prompts. If not provided, this will default first to the `sudo_password` on the SSH connection object, and then to the `password` on the SSH connection object. This parameter is only used when sudo_dash_S is provided.
		
		:return: The contents of the remote file.
		"""
		assert self._connection and self._connection.client, "Connection is not open"
		if sudo_dash_S:
			return self.exec(f'sudo -S cat {path}', sudo_password=sudo_password).stdout
		with self._connection.client.open_sftp() as ftp:
			ftp.chdir(cwd)
			file = ftp.file(path, "r")
			b = file.read()
			file.close()
			if encoding is not None:
				return b.decode(encoding)
			return b
	
	def write(self, path: str, contents: typing.Union[str, bytes], overwrite: bool = False, cwd: typing.Optional[str] = None, sudo_dash_S: bool=False, sudo_password: typing.Optional[str] = None):
		"""
		Write to a file using SFTP. The file will be created if it does not exist.

		:param path: Path to the file on the remote system.
		:param contents: The contents to write to the file.
		:param overwrite: Whether or not to overwrite the file's existing contents. If false, the contents will be appended instead.
		:param cwd: The current working directory. If `None`, no current working directory is used.
		:param sudo_dash_S: when 'True' use exec the command: 'sudo -S echo _contents_ > _path_ ' instead of using ftp.file.write() (cwd will be ignored)
		:param sudo_password: The password to use for sudo prompts. If not provided, this will default first to the `sudo_password` on the SSH connection object, and then to the `password` on the SSH connection object. This parameter is only used when sudo_dash_S is provided.
		"""
		assert self._connection and self._connection.client, "Connection is not open"
		# exec
		if sudo_dash_S:
			redirect_char = '>' if overwrite else '>>'
			return self.exec(f'sudo -S sh -c \'echo "{contents}" {redirect_char} {path}\'', sudo_password=sudo_password)

		# sftp
		mode = "a"
		if overwrite:
			mode = "w"
		with self._connection.client.open_sftp() as ftp:
			ftp.chdir(cwd)
			file = ftp.file(path, mode)
			file.write(contents)
			file.close()

	def download(self, path: str, dst: str, directory_contents_only: bool = False, overwrite: bool = False) -> typing.List[str]:
		"""
		Download a file or directory from the remote system using SFTP.

		:param path: Absolute path to the file or directory on the remote system.
		:param dst: The local destination file or directory to download to.
		:param directory_contents_only: If `True` and `path` points to a directory, then just the contents of the directory will be downloaded rather than the directory itself.
		:param overwrite: Whether to overwrite existing files.

		:return: A list of local paths to all files downloaded.
		"""
		assert self._connection and self._connection.client, "Connection is not open"
		log.info(f"{str(self)} Downloading \"{path}\" to \"{dst}\"...")
		assert os.path.isabs(path), f"{path} is not an absolute path"
		dst = os.path.abspath(dst)

		# Ensure the path exists
		path_stat = self.stat(path)
		if path_stat is None:
			raise exceptions.RemoteFileNotFoundError(self, path)

		if directory_contents_only and path_stat["isfile"]:
			raise exceptions.RemoteNotADirectoryError(self, path)

		# Get a mapping of remote paths to local paths
		# We need to test for different cases and handle each
		files_remote_to_local: typing.Dict[str, str] = {}
		directories_remote_to_local: typing.Dict[str, str] = {}

		if path_stat["isfile"]: # Single file download
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
				target = os.path.join(target, os.path.basename(path))

			files_remote_to_local[path] = target

		elif path_stat["isdir"]: # Directory download
			target = dst
			if os.path.isdir(target) and directory_contents_only:
				# Downloading directory contents into a directory
				pass
			elif os.path.isdir(target) and not directory_contents_only:
				# Downloading directory into a directory, download with the same name into the target
				target = os.path.join(target, os.path.basename(path))
			elif not os.path.exists(target) and directory_contents_only:
				# We cannot download the contents of a directory if the dst does not exist
				raise NotADirectoryError(f"{dst} is not a valid local directory")
			elif not os.path.exists(target) and not directory_contents_only:
				# Downloading directory under a new name, we just need to ensure that the parent directory exists
				parent = os.path.dirname(target)
				if not os.path.isdir(parent):
					raise NotADirectoryError(f"{parent} is not a valid local directory")

			files_remote_to_local = { file: os.path.join(target, file[len(path):].strip("/")) for file in self.exec(f"find {path} -type f -print", assert_status=0).stdout.split("\n") }
			directories_remote_to_local = { directory: os.path.join(target, directory[len(path):].strip("/")) for directory in self.exec(f"find {path} -type d -print", assert_status=0).stdout.split("\n") }

		if len(files_remote_to_local) == 0 and len(directories_remote_to_local) == 0:
			return [] # Nothing to do

		# Ensure that no local copies exist (if overwrite is not True)
		if not overwrite:
			for local_path in files_remote_to_local.values():
				if os.path.exists(local_path):
					raise FileExistsError(f"{local_path} already exists")
				if os.path.isdir(local_path):
					raise IsADirectoryError(f"{local_path} cannot be overwritten as it exists as a directory")

		# Create directories
		for local_path in directories_remote_to_local.values():
			os.makedirs(local_path, exist_ok=True)

		# # Begin downloading files
		with self._connection.client.open_sftp() as ftp:
			for remote_path, local_path in files_remote_to_local.items():
				log.debug(f"{self} Downloading {remote_path} to {local_path}")
				ftp.get(remote_path, local_path)

		return list(files_remote_to_local.values())
			
	def upload(self, src: str, dst: str, directory_contents_only: bool = False, overwrite: bool = False) -> typing.List[str]:
		"""
		Upload a local file or directory to this path on the remote system using SFTP.

		:param src: The local path to a file or directory to upload.
		:param dst: The absolute remote path to upload to.
		:param directory_contents_only: If `True` and `src` points to a directory, then only the contents of the directory will be uploaded rather than the directory itself.
		:param overwrite: Whether to overwrite existing files on the remote system.

		:return: A list of remote paths to all files uploaded.
		"""
		assert self._connection and self._connection.client, "Connection is not open"
		log.info(f"<{self}> Uploading \"{src}\" to \"{dst}\"...")
		assert os.path.isabs(dst), f"{dst} is not an absolute path"
		src = os.path.abspath(src)
		if not os.path.exists(src):
			raise FileNotFoundError(f"File or directory {src} not found")
	
		if directory_contents_only and not os.path.isdir(src):
			raise NotADirectoryError(f"{src} is not a valid local directory")

		dst_stat = self.stat(dst)

		# Get a mapping of local paths to remote paths
		# We need to test for different cases and handle each
		files_local_to_remote: typing.Dict[str, str] = {}
		directories_local_to_remote: typing.Dict[str, str] = {}

		if os.path.isfile(src): # Single file upload
			target = dst
			if dst_stat is None:
				# Target doesn't exist, we will upload under the name specified
				# Just ensure the parent directory does exist
				parent = os.path.dirname(target)
				if not self.isdir(parent):
					raise exceptions.RemoteNotADirectoryError(self, parent)
			else:
				# Target exists, we'll upload into the target with the same name
				if dst_stat["isdir"]:
					target = os.path.join(target, os.path.basename(src))
				elif overwrite:
					parent = os.path.dirname(target)
					if not self.isdir(parent):
						raise exceptions.RemoteNotADirectoryError(self, parent)
				else:
					raise exceptions.RemoteFileExistsError(self, target)

			files_local_to_remote[src] = target.rstrip("/")

		elif os.path.isdir(src): # Directory upload
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
				if not self.isdir(parent):
					raise exceptions.RemoteNotADirectoryError(self, parent)
			
			directories_local_to_remote[src] = target
			for root, directories, files in os.walk(src):
				for directory in directories:
					path = os.path.join(root, directory)
					directories_local_to_remote[path] = os.path.join(target, path[len(src):].lstrip("/")).rstrip("/")

				for file in files:
					path = os.path.join(root, file)
					files_local_to_remote[path] = os.path.join(target, path[len(src):].lstrip("/")).rstrip("/")

		if len(files_local_to_remote) == 0 and len(directories_local_to_remote) == 0:
			return [] # Nothing to do

		# Ensure that the upload will be valid (e.g. not overwriting files unless requested)
		# We only need to check in the case that the destination already exists
		if dst_stat is not None: 
			# Check the existence of all files and directories
			# Do this in a script so we can do this efficiently
			script = "\n".join([ f"stat -c '%F|%n' '{remote_path}' || true" for remote_path in [ *list(files_local_to_remote.values()), *list(directories_local_to_remote.values()) ] ])
			resp = self.exec_script(script, timeout=300)

			existing_remote_files = []
			existing_remote_directories = []
			for line in resp.stderr.strip().split("\n"):
				if not line:
					continue
				if "no such file" not in line.lower():
					raise exceptions.RemoteConnectionError(self, line)

			for line in resp.stdout.strip().split("\n"):
				if not line:
					continue
				filetype, filename = line.split("|", maxsplit=1)
				if "file" in filetype:
					existing_remote_files.append(filename.rstrip())
				elif "directory" in filetype:
					existing_remote_directories.append(filename.rstrip())

			for remote_file in files_local_to_remote.values():
				if remote_file in existing_remote_files and not overwrite:
					raise exceptions.RemoteFileExistsError(self, remote_file)
				if remote_file in existing_remote_directories:
					raise exceptions.RemoteIsADirectoryError(self, remote_file)

		# Determine the directories to create
		# We will be running mkdir with parents, so we only want the longest paths (to minimize the number of `mkdir` calls)
		dirs_to_make = []
		for remote_directory in directories_local_to_remote.values():
			dirname = remote_directory + "/"
			dirs_to_make = [ path for path in dirs_to_make if not dirname.startswith(path) ] # Remove any paths that are subsets of this path 
			is_parent = any([ path.startswith(dirname) for path in dirs_to_make ]) # Check if this is a parent of any existing path already
			if not is_parent:
				dirs_to_make.append(dirname)

		# Make directories
		# We will do this in a script to perform all operations in a single call
		# This is an optimization over making individual `mkdir` calls when the number of calls required is large
		script_contents = ""
		for dirname in dirs_to_make:
			script_contents += f"mkdir -p {dirname}\n"
		self.exec_script(script_contents, assert_status=0)
			
		# Begin uploading files
		with self._connection.client.open_sftp() as ftp:
			for local_path, remote_path in files_local_to_remote.items():
				log.debug(f"<{self}> Uploading \"{local_path}\" to \"{remote_path}\"")
				ftp.put(local_path, remote_path)

		return list(files_local_to_remote.values())

	def restart(self):
		"""
		Perform a graceful restart of the VM using `shutdown -r now`. This will close the current connection.
		"""
		self.exec("sudo shutdown -r now", pty=True)
		self.close()

	def shutdown(self):
		"""
		Attempt a graceful shutdown of the VM using `shutdown now`. This will close the current connection.
		"""
		self.exec("sudo shutdown now", pty=True)
		self.close()

	def time(self):
		"""
		Get the current time set on the remote host.

		:return: A `datetime` object.
		"""
		output = self.exec('date -u', assert_status=0).stdout.splitlines()[-1].strip()
		return parsetime(output).astimezone(datetime.timezone.utc)