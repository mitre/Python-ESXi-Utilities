from esxi_utils.vm.tools.guesttools import GuestTools, GuestToolsResponsePromise
from esxi_utils.util.response import Response
from esxi_utils.util import log, exceptions
import typing
import base64
import ntpath
import json
import os
import re

class WindowsGuestTools(GuestTools):
	"""
	Guest tools subclass specifically for interaction with a Windows operating system.

	Wrapper class for functionality related to VMware Tools on a Virtual Machine. The virtual machine must have VMware tools installed for
	any of the contained functions to work.

	:param vm: A `VirtualMachine` object to wrap. VMware tools must be installed on this virtual machine.
	"""
	def powershell_async(
		self, 
		username: str,
		password: str, 
		command: str, 
		cwd: typing.Optional[str] = None,
		powershell_path: str = "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
		out_stream_callback: typing.Optional[typing.Callable[[str], None]] = None
	):
		"""
		Runs a script in the guest operating system asynchronously using powershell.

		Unlike ``execute_program``, the command is executed as a standard powershell script and thus the full path to programs do not need to be provided. 
		Systems without powershell will fail. ``command`` may also be provided as a script, with newlines separating the commands to be run.

		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.
		:param command: The command or script to run.
		:param cwd: The working directory that the command should be run in.
		:param powershell_path: The path to the powershell executable.
		:param out_stream_callback: Optional callback to handle the stdout of commands. If not `None`, this will be called as a command's stdout becomes available. 
	
		:return: A `GuestToolsPowershellResponsePromise` object
		"""
		return GuestToolsPowershellResponsePromise(
			tools=self,
			username=username, 
			password=password, 
			command=command, 
			cwd=cwd,
			powershell_path=powershell_path, 
			out_stream_callback=out_stream_callback
		)

	def powershell(
		self, 
		username: str,
		password: str, 
		command: str, 
		cwd: typing.Optional[str] = None,
		powershell_path: str = "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
		timeout: typing.Optional[int] = 120,
		assert_status: typing.Optional[int] = None,
		out_stream_callback: typing.Optional[typing.Callable[[str], None]] = None
	) -> 'Response':
		"""
		Runs a script in the guest operating system using powershell. Unlike ``powershell_async``, this will block until the associated command has finished.

		Unlike ``execute_program``, the command is executed as a standard powershell script and thus the full path to programs do not need to be provided. 
		Systems without powershell will fail. ``command`` may also be provided as a script, with newlines separating the commands to be run.

		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.
		:param command: The command or script to run.
		:param cwd: The working directory that the command should be run in.
		:param powershell_path: The path to the powershell executable.
		:param timeout: The command timeout in seconds. Set to 0 or `None` to disable timeout.
		:param assert_status: Assert that the command exits with a certain status number. If `None`, no assertion is made and checking the status is left to the caller.
		:param out_stream_callback: Optional callback to handle the stdout of commands. If not `None`, this will be called as a command's stdout becomes available. 

		:return: A `Response` object
		"""
		return self.powershell_async(
			username=username, 
			password=password, 
			command=command, 
			cwd=cwd,
			powershell_path=powershell_path, 
			out_stream_callback=out_stream_callback
		).wait(assert_status=assert_status, timeout=timeout)

	def stat(
		self, 
		path: str, 
		username: str, 
		password: str, 
		powershell_path: str = "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
	) -> typing.Union[typing.Dict[str, typing.Any], None]:
		"""
		Get information about a file. PowerShell must be available on the system.

		Returned date formats in are seconds-since-Epoch.

		:param path: A path to a file or directory on the remote system.
		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.
		:param powershell_path: The path to the powershell executable.

		:return: A dict containing information about the file, or `None` if the file does not exist.
		"""
		path = ntpath.normpath(path)
		log.debug(f"{str(self)} Stat {path}")
		response = self.powershell(
			username=username,
			password=password,
			command=f"Get-Item {path} | ConvertTo-JSON",
			powershell_path=powershell_path
		)
		if response.status != 0 and (f"ObjectNotFound" in str(response.stderr) or f"ObjectNotFound" in str(response.stdout)):
			return None
		elif response.status != 0:
			raise exceptions.RemoteConnectionCommandError(self, response)
		
		results = json.loads(str(response.stdout).strip())

		def parse_date(datestr: str) -> float:
			date_match = re.search(r"Date\((\d+)\)", datestr)
			if not date_match:
				return -1
			date_value = date_match.group(1)
			if len(date_value) == 13:
				# In milliseconds
				return int(date_value) / 1000
			return int(date_value)

		return {
			"ProvidedPath": path,
			"Name": results["Name"],
			"FullName": results["FullName"],
			"Length": results.get("Length", 0),
			"IsFile": not str(results["Mode"]).startswith("d"),
			"IsDirectory": str(results["Mode"]).startswith("d"),
			"Mode": results["Mode"],
			"CreationTimeUtc": parse_date(results["CreationTimeUtc"]),
			"LastAccessTimeUtc": parse_date(results["LastAccessTimeUtc"]),
			"LastWriteTimeUtc": parse_date(results["LastWriteTimeUtc"]),
		}
	
	def bulkstat(self, paths: typing.List[str], username: str, password: str, powershell_path: str = "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe") -> typing.List[typing.Dict[str, typing.Any]]:
		"""
		Get information about one or more files.

		:param paths: The paths to the files or directories on the remote system.
		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.
		:param bash_path: The path to the bash executable.
		:param powershell_path: The path to the powershell executable.

		:return: A dict containing information about the file, or `None` if the file does not exist.
		"""
		paths = [ ntpath.normpath(p) for p in paths ]
		log.debug(f"{str(self)} Bulk Stat: {', '.join(paths)}")

		with self.use_temporary_file(username=username, password=password, extension=".ps1") as script_file:
			with self.use_temporary_file(username=username, password=password, extension=".stat") as output_file:
				script = f"""
$filenames = @({str(paths)[1:-1]})
foreach ($filename in $filenames) {{
    if (Test-Path $filename) {{
        Get-Item $filename | ConvertTo-Json -Compress | Out-File -Append -FilePath {output_file}
    }} else {{
        "Does not exist" | Out-File -Append -FilePath {output_file}
    }}
}}
""".strip()
				self.write_file(username=username, password=password, filepath=script_file, data=script)
				self.powershell(
					username=username,
					password=password,
					command=f"powershell -File {script_file}",
					powershell_path=powershell_path,
					assert_status=0
				)

				output: str = str(self.get_file(username=username, password=password, filepath=output_file, encoding="utf-16"))

		lines = output.strip().split("\n")
		if len(lines) != len(paths):
			raise RuntimeError(f"bulkstat: the number of output lines do not match the number of input files ({len(lines)} vs {len(paths)}). Raw Output:\n{output}")

		def parse_date(datestr: str) -> float:
			date_match = re.search(r"Date\((\d+)\)", datestr)
			if not date_match:
				return -1
			date_value = date_match.group(1)
			if len(date_value) == 13:
				# In milliseconds
				return int(date_value) / 1000
			return int(date_value)

		stats = list()
		for path, line in zip(paths, lines):
			if line.strip() == "Does not exist":
				stats.append({
					"ProvidedPath": path,
					"Exists": False,
					"Name": None,
					"FullName": None,
					"Length": None,
					"IsFile": None,
					"IsDirectory": None,
					"Mode": None,
					"CreationTimeUtc": None,
					"LastAccessTimeUtc": None,
					"LastWriteTimeUtc": None,
				})
				continue

			results = json.loads(line)
			stats.append({
				"ProvidedPath": path,
				"Exists": True,
				"Name": results["Name"],
				"FullName": results["FullName"],
				"Length": results.get("Length", 0),
				"IsFile": not str(results["Mode"]).startswith("d"),
				"IsDirectory": str(results["Mode"]).startswith("d"),
				"Mode": results["Mode"],
				"CreationTimeUtc": parse_date(results["CreationTimeUtc"]),
				"LastAccessTimeUtc": parse_date(results["LastAccessTimeUtc"]),
				"LastWriteTimeUtc": parse_date(results["LastWriteTimeUtc"]),
			})
		return stats

	def isfile(self, path: str, username: str, password: str, powershell_path: str = "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe") -> bool:
		"""
		Checks if the file exists and is a regular file.

		:param path: A path to a file on the remote system.
		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.
		:param powershell_path: The path to the powershell executable.
		
		:return: A boolean whether or not the file exists.
		"""
		path = ntpath.normpath(path)
		stat = self.stat(
			path, 
			username=username, 
			password=password,
			powershell_path=powershell_path
		)
		if stat is None:
			return False
		return stat["IsFile"]

	def isdir(self, path: str, username: str, password: str, powershell_path: str = "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe") -> bool:
		"""
		Checks if the directory exists.

		:param path: A path to a directory on the remote system.
		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.
		:param powershell_path: The path to the powershell executable.
		
		:return: A boolean whether or not the directory exists.
		"""
		path = ntpath.normpath(path)
		stat = self.stat(
			path, 
			username=username, 
			password=password,
			powershell_path=powershell_path
		)
		if stat is None:
			return False
		return stat["IsDirectory"]

	def download(
		self, 
		path: str, 
		dst: str, 
		username: str,
		password: str,
		directory_contents_only: bool = False, 
		overwrite: bool = False,
		powershell_path: str = "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
	) -> typing.List[str]:
		"""
		Download a file or directory from the remote system.

		:param path: Path to the file or directory on the remote system.
		:param dst: The local destination file or directory to download to.
		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.
		:param directory_contents_only: If `True` and `path` points to a directory, then just the contents of the directory will be downloaded rather than the directory itself.
		:param overwrite: Whether to overwrite existing files.
		:param powershell_path: The path to the powershell executable.

		:return: A list of local paths to all files downloaded.
		"""
		path = ntpath.normpath(path)
		log.info(f"{str(self)} Downloading \"{path}\" to \"{dst}\"...")
		dst = os.path.abspath(dst)
		basename = ntpath.basename(path)
		stat = self.stat(path, username=username, password=password, powershell_path=powershell_path)
		if stat is None:
			raise exceptions.RemoteFileNotFoundError(self, path)

		download_map: typing.Dict[str, str] = {} # Map download source -> destination
		if stat["IsFile"]:
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
				target = os.path.join(target, stat["Name"])
			elif not os.path.exists(target) and directory_contents_only:
				# We cannot download the contents of a directory if the dst does not exist
				raise NotADirectoryError(f"{dst} is not a valid local directory")
			elif not os.path.exists(target) and not directory_contents_only:
				# Downloading directory under a new name, we just need to ensure that the parent directory exists
				parent = os.path.dirname(target)
				if not os.path.isdir(parent):
					raise NotADirectoryError(f"{parent} is not a valid local directory")
			
			download_map = {}
			files_to_download = [ ntpath.join(path, filename) for filename in self.list_files(username=username, password=password, filepath=path) ]
			while len(files_to_download):
				stats = self.bulkstat(files_to_download, username=username, password=password, powershell_path=powershell_path)
				files_to_download = []
				for stat in stats:
					if stat["IsDirectory"]:
						files_to_download.extend([ ntpath.join(stat["FullName"], filename) for filename in self.list_files(username=username, password=password, filepath=stat["FullName"]) ])
						continue
					download_map[stat["FullName"]] = os.path.join(target, stat["FullName"][len(path):].replace("\\", "/").strip("/"))

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
		powershell_path: str = "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
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
		:param powershell_path: The path to the powershell executable.

		:return: A list of remote paths to all files uploaded.
		"""
		dst = ntpath.normpath(dst)
		log.info(f"<{self}> Uploading \"{src}\" to \"{dst}\"...")
		src = os.path.abspath(src)
		if not os.path.exists(src):
			raise FileNotFoundError(f"File or directory {src} not found")

		dst_stat = self.stat(dst, username=username, password=password, powershell_path=powershell_path)

		upload_map: typing.Dict[str, str] = {} # Map upload source -> destination
		if os.path.isfile(src):
			# Single file upload
			target = dst
			if dst_stat is None:
				# Target doesn't exist, we will upload under the name specified
				# Just ensure the parent directory does exist
				parent = ntpath.dirname(target)
				if not self.isdir(parent, username=username, password=password, powershell_path=powershell_path):
					raise exceptions.RemoteNotADirectoryError(self, parent)
			else:
				# Target exists, we'll upload into the target with the same name
				if not dst_stat["IsDirectory"]:
					raise exceptions.RemoteNotADirectoryError(self, dst)
				target = ntpath.join(target, os.path.basename(src))
			upload_map[src] = target
		elif os.path.isdir(src):
			# Directory upload
			target = dst
			target_exists = dst_stat is not None
			target_is_dir = dst_stat and dst_stat["IsDirectory"]
			if target_is_dir and directory_contents_only:
				# Uploading directory contents into a directory
				pass
			elif target_is_dir and not directory_contents_only:
				# Uploading directory into a directory, upload with the same name into the target
				target = ntpath.join(target, os.path.basename(src))
			elif not target_exists and directory_contents_only:
				# We cannot upload the contents of a directory if the dst does not exist
				raise exceptions.RemoteNotADirectoryError(self, target)
			elif not target_exists and not directory_contents_only:
				# Uploading directory under a new name, we just need to ensure that the parent directory exists
				parent = ntpath.dirname(target)
				if not self.isdir(parent, username=username, password=password, powershell_path=powershell_path):
					raise exceptions.RemoteNotADirectoryError(self, parent)
			
			for root, _, files in os.walk(src):
				for file in files:
					path = os.path.join(root, file)
					upload_map[path] = ntpath.join(target, ntpath.normpath(path[len(src):]).strip("\\"))

		if len(upload_map.keys()) == 0:
			return []

		for stat in self.bulkstat(list(upload_map.values()), username=username, password=password, powershell_path=powershell_path):
			if stat["Exists"] and stat["IsFile"] and not overwrite:
				raise exceptions.RemoteFileExistsError(self, stat["ProvidedPath"])
			if stat["Exists"] and stat["IsDirectory"]:
				raise exceptions.RemoteIsADirectoryError(self, stat["ProvidedPath"])

		# Determine the directories to create
		# We will be running mkdir with parents, so we only want the longest paths
		dirs_to_make = []
		for remotepath in upload_map.values():
			dirname = ntpath.dirname(remotepath).rstrip("\\") + "\\"
			dirs_to_make = [ path for path in dirs_to_make if not dirname.startswith(path) ] # Remove any paths that are subsets of this path 
			is_subpath = any([ path.startswith(dirname) for path in dirs_to_make ]) # Check if this is a subpath of any existing path already
			if not is_subpath:
				dirs_to_make.append(dirname)

		# Make directories
		self.powershell(
			username=username, 
			password=password,
			command=f"mkdir {str(dirs_to_make)[1:-1]} -Force -ea 0",
			powershell_path=powershell_path,
			assert_status=0
		)

		# Begin uploading files
		for localpath, remotepath in upload_map.items():
			log.debug(f"<{self}> Uploading \"{localpath}\" to \"{remotepath}\"")
			with open(localpath, "rb") as f:
				self.write_file(username=username, password=password, filepath=remotepath, data=f.read())

		return list(upload_map.values())



class GuestToolsPowershellResponsePromise(GuestToolsResponsePromise):
	"""
	Encapsulates a Promise for a result of an GuestTools Powershell command.

	:param tools: The WindowsGuestTools instance from which this promise originates.
	:param username: The username of the virtual machine user.
	:param password: The password of the virtual machine user.
	:param command: The command or script to run.
	:param cwd: The working directory that the command should be run in.
	:param powershell_path: The path to the powershell executable.
	:param out_stream_callback: Optional callback to handle the stdout of commands. If not `None`, this will be called as a command's stdout becomes available. 
	"""
	def __init__(
		self, 
		tools: WindowsGuestTools, 
		username: str,
		password: str, 
		command: str, 
		cwd: typing.Optional[str] = None,
		powershell_path: str = "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
		out_stream_callback: typing.Optional[typing.Callable[[str], None]] = None
	):
		assert isinstance(powershell_path, str), "powershell_path must be a string"

		self._powershell_path = powershell_path
		self._exitcodefile = None

		super().__init__(
			tools=tools, 
			username=username, 
			password=password, 
			command=command,
			cwd=cwd,
			make_output_available=True,
			out_stream_callback=out_stream_callback
		)

	def _encode_command(self, command_string: str) -> str:
		"""
		Base64 encode the given command so that it can be passed to powershell.

		:param command_string: The command to encode.
		
		:return: The base64 encoded command.
		"""
		return base64.b64encode(str.encode(command_string, encoding="utf_16_le")).decode()

	def _setup(self, make_output_available: bool = False) -> str:
		"""
		Perform any setup necessary prior to starting the command.

		:param make_output_available: Whether or not it is requested to make the output of the command available.
		
		:return: The command to run.
		"""
		self._exitcodefile = self._tools.create_temporary_file(self._username, self._password, ".log")
		encoded_command = self._encode_command(self._command)

		run_script = ""
		if make_output_available:
			self._stdoutfile = self._tools.create_temporary_file(self._username, self._password, ".out")
			self._stderrfile = self._tools.create_temporary_file(self._username, self._password, ".err")

			run_script = f"""
			$process = Start-Process "powershell.exe" -ArgumentList "-NonInteractive -EncodedCommand {encoded_command}" -RedirectStandardError "{self._stderrfile}" -RedirectStandardOutput "{self._stdoutfile}" -PassThru -NoNewWindow -Wait
			$process.ExitCode | Out-File -FilePath "{self._exitcodefile}"
			"""
		else:
			run_script = f"""
			$process = Start-Process "powershell.exe" -ArgumentList "-NonInteractive -EncodedCommand {encoded_command}" -PassThru -NoNewWindow -Wait
			$process.ExitCode | Out-File -FilePath "{self._exitcodefile}"
			"""
		run_script = "\r\n".join([ line.strip() for line in run_script.replace("\r", "").split("\n") ])

		exec_command = f"""Start-Process "{self._powershell_path}" -ArgumentList "-NonInteractive -EncodedCommand {self._encode_command(run_script)}" -NoNewWindow -Wait"""
		return f"{self._powershell_path} -EncodedCommand {self._encode_command(exec_command)}" 

	def _format_response(self, response: Response) -> Response:
		"""
		Perform post-processing on a result. This will occur when a command finishes executing but before any files are cleaned up.

		:param response: The result of the command.

		:return: The new result.
		"""
		if response.status == 0:
			try:
				assert self._exitcodefile, "No exitcode file"
				status_code = self._tools.get_file(self._username, self._password, self._exitcodefile, encoding="utf-16").strip()
				response.status = int(status_code)
			except ValueError as e:
				print(e)
				response.status = 1
		return response

	def _cleanup(self):
		"""
		Clean up any files or other resources after the process has finished.
		"""
		super()._cleanup()
		if self._exitcodefile:
			self._tools.delete_file(self._username, self._password, self._exitcodefile)
			self._exitcodefile = None
