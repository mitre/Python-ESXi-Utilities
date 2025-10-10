from esxi_utils.util import log, exceptions
import pyVmomi
import os
import re
import urllib.request
import urllib.parse
import typing
import ssl

if typing.TYPE_CHECKING:
	from esxi_utils.client import ESXiClient
	from esxi_utils.vm.virtualmachine import VirtualMachine

class DatastoreList:
	"""
	The collection of datastores on an ESXi host.

	:param client: The `ESXiClient` object for the ESXi server to use.
	"""
	def __init__(self, client: 'ESXiClient'):
		self._client = client

	def __iter__(self) -> typing.Iterator['Datastore']:
		datastores = []
		# The host system keeps a record of datastore objects, but I didn't find a reference to the datastore
		# Ideally, we could get the datastore ID from the '_host_system' object instead of having to iterate
		if self._client._child_hostname:
			client_moIds = []
			for ds in self._client._get_datastore_objects_from_host_system():
				client_moIds.append(ds._moId)
		# iterate through all datastores
		for dc in self._client._get_vim_objects(pyVmomi.vim.Datacenter, query_root=True):
			for ds in dc.datastore:
				# filter out datastores not relevant to this '_host_system'
				if self._client._child_hostname and ds._moId not in client_moIds:
					continue
				datastores.append(Datastore(self._client, dc._moId, ds._moId))
		return iter(datastores)

	def __getitem__(self, name) -> 'Datastore':
		return self.get(name)

	def __contains__(self, name: str):
		return self.exists(name)

	@property
	def items(self) -> typing.List['Datastore']:
		"""
		A list of all items
		"""
		return list(self)

	def find(self, name: str) -> typing.Union['Datastore', None]:
		"""
		Get a datastore on the ESXi host.

		:param name: The name of the datastore to get.

		:return: A `Datastore` object, or `None` if not found.
		"""
		ds = [ds for ds in self if ds.name == name]
		if len(ds) == 0:
			return None
		return ds[0]

	def get(self, name: str) -> 'Datastore':
		"""
		Get a datastore on the ESXi host and raise an exception if not found.

		:param name: The name of the datastore to get.

		:return: A `Datastore` object
		"""
		ds = self.find(name)
		if ds is None:
			raise exceptions.DatastoreNotFoundError(name)
		return ds

	@property
	def names(self) -> typing.List[str]:
		"""
		List the names of all datastores on the ESXi host.

		:return: A list of names (strings).
		"""
		return [ ds.name for ds in self ]

	def exists(self, name: str) -> bool:
		"""
		Return whether or not the given datastore exists.

		:param name: The name of the datastore.

		:return: A boolean whether the datastore exists.
		"""
		return name in self.names

	def resolve(self, name_or_obj: typing.Union[str, 'Datastore']) -> 'Datastore':
		"""
		Resolve a type to an `Datastore` object. Raises an error if the datastore cannot be resolved.

		:param name_or_obj: The value to resolve. If a string, an `Datastore` is searched for by name. If already an `Datastore` object, this simply asserts the datastore exists.

		:return: An `Datastore` object.
		"""
		if isinstance(name_or_obj, str):
			name_or_obj = self.get(name=name_or_obj)
		if not isinstance(name_or_obj, Datastore) or not self.exists(name_or_obj.name):
			raise exceptions.DatastoreNotFoundError(name_or_obj)
		return name_or_obj

	def __str__(self):
		return f"<{type(self).__name__} for {self._client.username}@{self._client.hostname}>"

	def __repr__(self):
		return str(self)


class Datastore:
	"""
	A datastore on the ESXi host.
	"""
	def __init__(self, client: 'ESXiClient', datacenter_id: str, datastore_id: str):
		self._client = client
		self._datacenter_id = datacenter_id
		self._datastore_id = datastore_id

	@property
	def name(self) -> str:
		"""
		Get the name of the this datastore.

		:return: The datastore name.
		"""
		return self._datastore.summary.name

	@property
	def file_system_type(self) -> str:
		"""
		Get the type of file system volume, such as VMFS or NFS.

		:return: The file system type
		"""
		return self._datastore.summary.type

	@property
	def nfs(self) -> bool:
		"""
		Return whether or not this datastore is a network file system.

		:return: A boolean whether the file system type is NFS.
		"""
		return self.file_system_type == "NFS"

	@property
	def path(self) -> str:
		"""
		Get the path of the datastore on the ESXi host (i.e. /vmfs/volumes/<id>).

		:return: The path of the datastore
		"""
		return self._datastore.summary.url

	@property
	def accessible(self) -> bool:
		"""
		Get the connectivity status of this datastore. If false, this means the datastore is not accessible and certain properties (i.e. this datastore's capacity and freespace properties) cannot be validated.

		:return: Whether or not the datastore is accessible.
		"""
		return self._datastore.summary.accessible

	@property
	def root(self) -> 'DatastoreFile':
		"""
		Get the root filepath for this datastore.
		"""
		return DatastoreFile(self, ".")

	@property
	def vms(self) -> typing.List['VirtualMachine']:
		"""
		Virtual machines stored on this datastore. 
		"""
		vm_ids = [ str(vm._moId) for vm in self._datastore.vm ]
		return [ vm for vm in self._client.vms.items if vm.id in vm_ids]

	def filepath(self, path: str) -> 'DatastoreFile':
		"""
		Get a `DatastoreFile` object for the provided path.
		"""
		return DatastoreFile(self, path)

	def capacity(self, unit: str = "B") -> int:
		"""
		Get the capacity of this datastore in the provided unit.
		
		:param unit: The unit of measurement to use (one of: B, KB, MB, GB, TB).

		:return: The capacity of the datastore in the provided unit.
		"""
		unit_orders = ["B", "KB", "MB", "GB", "TB"]
		assert unit in unit_orders, f"unit must be one of: {', '.join(unit_orders)}"
		return self._datastore.summary.capacity / pow(1024, unit_orders.index(unit))

	def freespace(self, unit: str = "B") -> int:
		"""
		Get the free space of this datastore in the provided unit.
		
		:param unit: The unit of measurement to use (one of: B, KB, MB, GB, TB).

		:return: The free space of the datastore in the provided unit.
		"""
		unit_orders = ["B", "KB", "MB", "GB", "TB"]
		assert unit in unit_orders, f"unit must be one of: {', '.join(unit_orders)}"
		return self._datastore.summary.freeSpace / pow(1024, unit_orders.index(unit))

	def used_disk_space(self, unit: str = "B") -> int:
		"""
		Get the used space of this datastore in the provided unit.
		
		:param unit: The unit of measurement to use (one of: B, KB, MB, GB, TB).

		:return: The used space of the datastore in the provided unit.
		"""
		unit_orders = ["B", "KB", "MB", "GB", "TB"]
		assert unit in unit_orders, f"unit must be one of: {', '.join(unit_orders)}"
		return self.capacity(unit) - self.freespace(unit)

	def disk_usage_percent(self) -> float:
		"""
		Returns the percentage usage of the disk space of this drive
		"""
		return self.used_disk_space() / self.capacity()

	@property
	def _datacenter(self):
		dc = pyVmomi.vim.Datacenter(self._datacenter_id)
		dc._stub = self._client._service_instance._stub
		return dc

	@property
	def _datastore(self):
		ds = pyVmomi.vim.Datastore(self._datastore_id)
		ds._stub = self._client._service_instance._stub
		return ds

	def __str__(self):
		return f"<{type(self).__name__} '{self.name}' on {self._client.hostname}>"

	def __repr__(self):
		return str(self)


class DatastoreFile:
	"""
	Class representing a filepath on a datastore. 
	It is possible to navigate using the div operator (i.e. `filepath = filepath / "path" / "to" / "file"`) or by indexing (i.e. `filepath = filepath["path"]["to"]["file"]`)

	:param datastore: The `Datastore` object.
	:param relpath: The relative path to the file on the datastore.
	"""
	def __init__(self, datastore: 'Datastore', relpath: str):
		self._datastore = datastore
		self._relpath = self._sanitize(relpath)

	def	__truediv__(self, path: str) -> 'DatastoreFile':
		return self.join(path)

	def __getitem__(self, path) -> 'DatastoreFile':
		return self.join(path)

	def __iter__(self):
		return iter(self.ls(recursive=False))

	def __contains__(self, name: str):
		return self.join(name).exists

	def join(self, *paths) -> 'DatastoreFile':
		"""
		Join this path with one or more additional path components. Does not check that this path exists.
		"""
		return DatastoreFile(self.datastore, os.path.join(self.relpath, *paths))

	@property
	def datastore(self) -> 'Datastore':
		"""
		The datastore for this filepath.
		"""
		return self._datastore

	@property
	def relpath(self) -> str:
		"""
		Return the relative path for this filepath in the datastore.
		"""
		return self._relpath

	@property
	def path(self) -> str:
		"""
		Return the path for this filepath in the datastore.
		"""
		return f"[{self.datastore.name}] {self.relpath}"

	@property
	def abspath(self) -> str:
		"""
		The absolute path for this filepath in the datastore.
		"""
		return os.path.join(self.datastore.path, self.relpath)

	@property
	def filename(self) -> str:
		"""
		The final component of the file path (basename).
		"""
		return os.path.basename(self.relpath)

	@property
	def parent(self) -> typing.Union['DatastoreFile', None]:
		"""
		The parent directory of this file. If there is no parent, this returns `None`.
		"""
		if self.relpath == ".":
			return None
		return DatastoreFile(self.datastore, os.path.dirname(self.relpath))

	def _get_files(self, recursive=False):
		"""
		List files in the datastore.

		:param recursive: Whether or not to list files recursively (i.e. list path and all subfolders).

		:return: A dict mapping file paths to metadata
		"""
		log.debug(f"<{self.path}> Getting files (recursive={recursive})...")
		spec = pyVmomi.vim.host.DatastoreBrowser.SearchSpec(details=pyVmomi.vim.host.DatastoreBrowser.FileInfo.Details(fileSize=True))
		task = None
		if recursive:
			task = self.datastore._datastore.browser.SearchDatastoreSubFolders_Task(datastorePath=self.path, searchSpec=spec)	
		else:
			task = self.datastore._datastore.browser.SearchDatastore_Task(datastorePath=self.path, searchSpec=spec)

		results = self.datastore._client._wait_for_task(task)
		if not isinstance(results, list):
			results = [results]
		paths = {}
		base = f"[{self.datastore.name}]"
		for result in results:
			folder_path = result.folderPath.replace(base, "", 1).strip()
			for file in result.file:
				path = os.path.join(folder_path, file.path)
				path = self._sanitize(path)
				paths[path] = {
					"size": file.fileSize,
					"isfile": not isinstance(file, pyVmomi.vim.host.DatastoreBrowser.FolderInfo),
				}
		return paths

	def ls(self, recursive: bool = False) -> typing.List['DatastoreFile']:
		"""
		List all files and directories in this directory.

		:param: List files recursively.

		:return: A list of `DatastoreFile` objects
		"""
		return [ DatastoreFile(self.datastore, path) for path in self._get_files(recursive=recursive).keys() ]

	@property
	def files(self) -> typing.List['DatastoreFile']:
		"""
		List files in this directory.
		"""
		return [ DatastoreFile(self.datastore, path) for path, stat in self._get_files(recursive=False).items() if stat["isfile"] ]

	@property
	def dirs(self) -> typing.List['DatastoreFile']:
		"""
		List directories in this directory.
		"""
		return [ DatastoreFile(self.datastore, path) for path, stat in self._get_files(recursive=False).items() if not stat["isfile"] ]

	@property
	def stat(self) -> typing.Dict[str, typing.Any]:
		"""
		Information on this file or directory. Raises a `DatastoreFileNotFoundError` exception if this file does not exist
		"""
		log.debug(f"<{self.path}> Stat...")
		if self.parent is None:
			result = { "size": 0, "isfile": False }
			log.debug(f"<{self.path}> Stat result (root): {result}")
			return result
		try:
			folder_contents = self.parent._get_files(recursive=False)
		except exceptions.ESXiAPIError as e:
			if "vim.fault.FileNotFound" in str(e):
				raise exceptions.DatastoreFileNotFoundError(self.datastore, self.relpath)
			log.warn(f'Exception getting folder_contents in stat: {str(e)}')				
		if self.relpath not in folder_contents:
			raise exceptions.DatastoreFileNotFoundError(self.datastore, self.relpath)
		result = folder_contents[self.relpath]
		log.debug(f"<{self.path}> Stat result: {result}")
		return result

	@property
	def exists(self) -> bool:
		"""
		Whether or not this file exists on the datastore.
		"""
		try:
			return self.stat is not None
		except exceptions.DatastoreFileNotFoundError:
			return False

	@property
	def isfile(self) -> bool:
		"""
		Whether or not this is a file on the datastore.
		"""
		try:
			return self.stat["isfile"]
		except exceptions.DatastoreFileNotFoundError:
			return False

	@property
	def isdir(self) -> bool:
		"""
		Whether or not this is a directory on the datastore.
		"""
		try:
			return not self.stat["isfile"]
		except exceptions.DatastoreFileNotFoundError:
			return False

	def read(self, encoding: typing.Optional[str] = 'utf-8') -> typing.Union[str, bytes]:
		"""
		Returns the contents of a file on the remote server.

		:param encoding: The encoding to use when decoding the file. If `None`, no decoding is performed and bytes will be returned.

		:return: The file contents as a string (or bytes).
		"""
		log.debug(f"<{self.path}> Reading (encoding='{encoding}')...")
		if not self.isfile:
			raise exceptions.DatastoreIsADirectoryError(self.datastore, self.relpath)

		params = {"dsName": self.datastore._datastore.info.name, "id": self.datastore._datacenter._moId}
		query_string = urllib.parse.urlencode(params)
		url = "https://" + self.datastore._client.hostname + ":443/folder/" + urllib.parse.quote_plus(self.relpath) + "?" + query_string

		# Download the file
		ctx = ssl.create_default_context()
		ctx.check_hostname = False
		ctx.verify_mode = ssl.CERT_NONE
		try:
			request = urllib.request.Request(url)
			request.add_header("Content-Type", "application/octet-stream")
			child_client = self.datastore._client._child_esxi_client_instance
			cookie = self.datastore._client._service_instance._stub.cookie if child_client is None else child_client._service_instance._stub.cookie
			request.add_header("Cookie", cookie)

			with urllib.request.urlopen(request, context=ctx) as response:
				response_content = response.read()
				if not response.status == 200:
					raise exceptions.DatastoreError(self.datastore, f"Error while getting file {self.relpath} (status {response.status}): {response_content}")
				if encoding:
					return response_content.decode(encoding=encoding)
				return response_content
		except (urllib.error.URLError, urllib.error.HTTPError) as error:
			raise exceptions.DatastoreError(self.datastore, f"Error while getting file {self.relpath}: {error.reason}")

	def write(self, contents: typing.Union[str, bytes]):
		"""
		Writes to the remote file. The file will be created if it does not exist. If it does exist, the contents will be overwritten.

		:param path: The path to a file, relative to this datastore.
		:param contents: The contents to write to the file. 
		"""
		log.debug(f"<{self.path}> Writing (len={len(contents)})...")
		if not self.isfile:
			raise exceptions.DatastoreIsADirectoryError(self.datastore, self.relpath)

		params = {"dsName": self.datastore._datastore.info.name, "id": self.datastore._datacenter._moId}
		query_string = urllib.parse.urlencode(params) 
		url = "https://" + self.datastore._client.hostname + ":443/folder/" + urllib.parse.quote_plus(self.relpath) + "?" + query_string

		if isinstance(contents, str):
			contents = str.encode(contents)

		# Upload the file
		ctx = ssl.create_default_context()
		ctx.check_hostname = False
		ctx.verify_mode = ssl.CERT_NONE
		try:
			request = urllib.request.Request(url, data=contents, method='PUT')
			request.add_header("Content-Type", "application/octet-stream")
			child_client = self.datastore._client._child_esxi_client_instance
			cookie = self.datastore._client._service_instance._stub.cookie if child_client is None else child_client._service_instance._stub.cookie
			request.add_header("Cookie", cookie)

			with urllib.request.urlopen(request, context=ctx) as response:
				response_content = response.read()
				if not response.status >= 200 and not response.status < 300:
					raise exceptions.DatastoreError(self.datastore, f"Error while writing file {self.relpath} (status {response.status}): {response_content}")
		except (urllib.error.URLError, urllib.error.HTTPError) as error:
			raise exceptions.DatastoreError(self.datastore, f"Error while writing file {self.relpath}: {error.reason}")

	def download(self, dst: str, directory_contents_only: bool = False, overwrite: bool = False) -> typing.List[str]:
		"""
		Download this file or directory from the datastore.

		:param dst: The local destination file or directory to download to.
		:param directory_contents_only: If `True` and this is a directory, then just the contents of the directory will be downloaded rather than the directory itself.
		:param overwrite: Whether to overwrite existing files.

		:return: A list of local paths to all files downloaded.
		"""
		log.debug(f"<{self.path}> Downloading to \"{dst}\"...")
		dst = os.path.abspath(dst)
		if not self.exists:
			raise exceptions.DatastoreFileNotFoundError(self.datastore, self.relpath)

		download_map = {} # Map download source -> destination
		if self.isfile:
			# Single file download
			target = dst
			parent = os.path.dirname(target)
			if not os.path.isdir(parent):
				raise NotADirectoryError(f"{parent} is not a valid local directory")
			# target exists
			if os.path.exists(target):
				# complete the path to the file if the input is just the directory
				if os.path.isdir(target):
					target = os.path.join(target, self.filename)
				# else: assume the target is already the full path to the file
			download_map[self.relpath] = target
		else:
			# Directory download
			target = dst
			if os.path.isdir(target) and directory_contents_only:
				# Downloading directory contents into a directory
				pass
			elif os.path.isdir(target) and not directory_contents_only:
				# Downloading directory into a directory, download with the same name into the target
				target = os.path.join(target, self.filename)
			elif not os.path.exists(target) and directory_contents_only:
				# We cannot download the contents of a directory if the dst does not exist
				raise NotADirectoryError(f"{dst} is not a valid local directory")
			elif not os.path.exists(target) and not directory_contents_only:
				# Downloading directory under a new name, we just need to ensure that the parent directory exists
				parent = os.path.dirname(target)
				if not os.path.isdir(parent):
					raise NotADirectoryError(f"{parent} is not a valid local directory")
			
			download_map = { file: os.path.join(target, file[len(self.relpath):].strip("/")) for file, stat in self._get_files(recursive=True).items() if stat["isfile"] }

		if len(download_map.keys()) == 0:
			return []

		for target in download_map.values():
			if os.path.exists(target) and not overwrite:
				raise FileExistsError(f"{target} already exists")
			if os.path.isdir(target):
				raise IsADirectoryError(f"{target} cannot be overwritten as it exists as a directory")

		# Begin downloading files
		params = {"dsName": self.datastore._datastore.info.name, "id": self.datastore._datacenter._moId}
		query_string = urllib.parse.urlencode(params) 

		ctx = ssl.create_default_context()
		ctx.check_hostname = False
		ctx.verify_mode = ssl.CERT_NONE

		for remotepath, localpath in download_map.items():
			log.debug(f"<{self.path}> Downloading {remotepath} to {localpath}")
			url = "https://" + self.datastore._client.hostname + ":443/folder/" + urllib.parse.quote_plus(remotepath) + "?" + query_string
			request = urllib.request.Request(url)
			request.add_header("Content-Type", "application/octet-stream")
			child_client = self.datastore._client._child_esxi_client_instance
			cookie = self.datastore._client._service_instance._stub.cookie if child_client is None else child_client._service_instance._stub.cookie
			request.add_header("Cookie", cookie)
			os.makedirs(os.path.dirname(localpath), exist_ok=True)
			try:
				with urllib.request.urlopen(request, context=ctx) as response, open(localpath, 'wb') as out_file:
					if not response.status == 200:
						raise exceptions.DatastoreError(self.datastore, f"Error while downloading file {remotepath} (status {response.status}): {response.read()}")
					while True:
						content = response.read(256 * 1024)
						if len(content) == 0:
							# Done
							break
						out_file.write(content)
					out_file.flush()
					os.fsync(out_file.fileno())
			except (urllib.error.URLError, urllib.error.HTTPError) as error:
				raise exceptions.DatastoreError(self.datastore, f"Error while downloading file {remotepath}: {error.reason}")
		return list(download_map.values())

	def upload(self, src: str, directory_contents_only: bool = False, overwrite: bool = False) -> typing.List['DatastoreFile']:
		"""
		Upload a file or directory to this path on the datastore.

		:param src: The local path to a file or directory to upload.
		:param directory_contents_only: If `True` and `src` points to a directory, then only the contents of the directory will be uploaded rather than the directory itself.
		:param overwrite: Whether to overwrite existing files on the datastore.

		:return: A list of `DatastoreFile` objects for all files uploaded.
		"""
		log.info(f"<{self.path}> Uploading \"{src}\"...")
		src = os.path.abspath(src)
		if not os.path.exists(src):
			raise FileNotFoundError(f"File or directory {src} not found")

		upload_map = {} # Map upload source -> destination
		if os.path.isfile(src):
			# Single file upload
			target = self
			if not target.exists:
				# Target doesn't exist, we will upload under the name specified
				# Just ensure the parent directory does exist
				if not target.parent.isdir:
					raise exceptions.DatastoreNotADirectoryError(self.datastore, target.parent.relpath)
			else:
				# Target exists, we'll upload into the target with the same name
				if not target.isdir:
					raise exceptions.DatastoreNotADirectoryError(self.datastore, target.relpath)
				target = target / os.path.basename(src)
			upload_map[src] = target
		elif os.path.isdir(src):
			# Directory upload
			target = self
			target_exists = target.exists
			target_is_dir = target.isdir
			if target_is_dir and directory_contents_only:
				# Uploading directory contents into a directory
				pass
			elif target_is_dir and not directory_contents_only:
				# Uploading directory into a directory, upload with the same name into the target
				target = target / os.path.basename(src)
			elif not target_exists and directory_contents_only:
				# We cannot upload the contents of a directory if the dst does not exist
				raise exceptions.DatastoreNotADirectoryError(self.datastore, target.relpath)
			elif not target_exists and not directory_contents_only:
				# Uploading directory under a new name, we just need to ensure that the parent directory exists
				if not target.parent.isdir:
					raise exceptions.DatastoreNotADirectoryError(self.datastore, target.parent.relpath)
			
			for root, _, files in os.walk(src):
				for file in files:
					path = os.path.join(root, file)
					upload_map[path] = target / path[len(src):].strip("/")

		if len(upload_map.keys()) == 0:
			return []

		for target in upload_map.values():
			if target.exists and not overwrite:
				raise exceptions.DatastoreFileExistsError(self.datastore, target.relpath)
			if target.isdir:
				raise exceptions.DatastoreIsADirectoryError(self.datastore, target.relpath)

		# Begin uploading files
		params = {"dsName": self.datastore._datastore.info.name, "id": self.datastore._datacenter._moId}
		query_string = urllib.parse.urlencode(params) 

		ctx = ssl.create_default_context()
		ctx.check_hostname = False
		ctx.verify_mode = ssl.CERT_NONE

		for localpath, remotepath in upload_map.items():
			log.debug(f"<{self.path}> Uploading {localpath} to {remotepath.relpath}")
			url = "https://" + self.datastore._client.hostname + ":443/folder/" + urllib.parse.quote_plus(remotepath.relpath) + "?" + query_string

			with open(localpath, mode='rb') as file:
				request = urllib.request.Request(url, data=file, method='PUT')
				request.add_header("Content-Type", "application/octet-stream")
				child_client = self.datastore._client._child_esxi_client_instance
				cookie = self.datastore._client._service_instance._stub.cookie if child_client is None else child_client._service_instance._stub.cookie
				request.add_header("Cookie", cookie)
				remotepath.parent.mkdir(parents=True)
				try:
					with urllib.request.urlopen(request, context=ctx) as response: # if you add timeout=#, it does timeout
						response_content = str(response.read())
						if not response.status >= 200 and not response.status < 300:
							raise exceptions.DatastoreError(self.datastore, f"Error while uploading file {localpath} (status {response.status}): {response_content}")
				except (urllib.error.URLError, urllib.error.HTTPError) as error:
					raise exceptions.DatastoreError(self.datastore, f"Error while uploading file {localpath}: {error.reason}")

		return list(upload_map.values())

	def mkdir(self, parents: bool = False):
		"""
		Create this folder (directory) in the datastore. If the directory already exists, this does nothing.

		:param parents: Make parent directories as needed.
		"""
		log.debug(f"<{self.path}> Mkdir...")
		try:
			file_manager = self.datastore._client._service_instance.RetrieveContent().fileManager
			file_manager.MakeDirectory(name=self.path, datacenter=self.datastore._datacenter, createParentDirectories=parents)
		except pyVmomi.vim.fault.FileAlreadyExists:
			pass

	def copy(self, to: 'DatastoreFile', force: bool = False):
		"""
		Copy this file or directory to another location.

		:param to: The `DatastoreFile` to the destination file or directory.
		:param force: If true, overwrite any identically named file at the destination.
		"""
		assert isinstance(to, DatastoreFile), "The `to` parameter must be of type DatastoreFile"
		log.debug(f"<{self.path}> Copying to \"{to.path}\"...")
		if not self.exists:
			raise exceptions.DatastoreFileNotFoundError(self.datastore, self.relpath)
		
		file_manager = self.datastore._client._service_instance.RetrieveContent().fileManager
		self.datastore._client._wait_for_task(file_manager.CopyDatastoreFile_Task(
			sourceName=self.path,
			sourceDatacenter=self.datastore._datacenter,
			destinationName=to.path,
			destinationDatacenter=to.datastore._datacenter,
			force=force
		))

	def merge(self, to: 'DatastoreFile', force: bool = False):
		"""
		Merge (copy) the contents of this directory to another.

		:param to: The 'DatastoreFile' for the destination directory.
		:param force: If true, overwrite any identically named file at the destination.
		"""
		assert isinstance(to, DatastoreFile), "The `to` parameter must be of type DatastoreFile"
		log.debug(f"<{self.path}> Merging to \"{to.path}\"...")
		if not self.isdir:
			raise exceptions.DatastoreNotADirectoryError(self.datastore, self.relpath)
		if not to.isdir:
			raise exceptions.DatastoreNotADirectoryError(to.datastore, to.relpath)
		
		for file in self.files:
			file.copy(to / file.filename, force=force)

	def move(self, to: 'DatastoreFile', force: bool = False):
		"""
		Move this file or directory to another location.

		:param to: The 'DatastoreFile' for the destination.
		:param force: If true, overwrite any identically named file at the destination.
		"""
		assert isinstance(to, DatastoreFile), "The `to` parameter must be of type DatastoreFile"
		log.debug(f"<{self.path}> Moving to \"{to.path}\"...")
		if not self.exists:
			raise exceptions.DatastoreFileNotFoundError(self.datastore, self.relpath)
		
		file_manager = self.datastore._client._service_instance.RetrieveContent().fileManager
		self.datastore._client._wait_for_task(file_manager.MoveDatastoreFile_Task(
			sourceName=self.path,
			sourceDatacenter=self.datastore._datacenter,
			destinationName=to.path,
			destinationDatacenter=to.datastore._datacenter,
			force=force
		))

	def remove(self):
		"""
		Removes this file or directory on the datastore. Folder deletes are always recursive. If the path does not exist, this does nothing.
		"""
		log.debug(f"<{self.path}> Removing...")
		if not self.exists:
			return
		file_manager = self.datastore._client._service_instance.RetrieveContent().fileManager
		self.datastore._client._wait_for_task(file_manager.DeleteDatastoreFile_Task(
			name=self.path,
			datacenter=self.datastore._datacenter,
		))

	def register_vm(self, name: typing.Optional[str] = None) -> 'VirtualMachine':
		"""
		Register a new VM using this file. This must be a valid VMX file, or a directory containing a single VMX file

		:param name: The name to set for the VM. If `None`, the VM name will be derived from the VMX file.

		:return: A `VirtualMachine` object (or subtype) for the new VM.
		"""
		assert isinstance(name, str) or name is None

		log.debug(f"<{self.path}> Registering VM (name={name})...")
		if self.isfile and not self.filename.lower().endswith(".vmx"):
			raise exceptions.DatastoreError(self.datastore, f"{self.relpath} is not a valid .vmx file")
		
		target = self
		if self.isdir:
			files =  [ file for file in target.files if file.filename.lower().endwith(".vmx") ]
			if len(files) == 0:
				raise exceptions.DatastoreError(self.datastore, f"No .vmx file found in {target.relpath}")
			if len(files) > 1:
				raise exceptions.DatastoreError(self.datastore, f"Multiple .vmx files found in {target.relpath}: {', '.join([file.relpath for file in files])})")
			target = files[0]
			log.debug(f"<{self.path}> Registering VM from found VM file: {target.relpath}")
		
		destination_host = self.datastore._client._host_system
		vim_vm = self.datastore._client._wait_for_task(self.datastore._datacenter.vmFolder.RegisterVM_Task(
			path=target.path,
			name=name,
			asTemplate=False,
			pool=destination_host.parent.resourcePool,
			host=destination_host
		))
		return self.datastore._client.vms.get(str(vim_vm._moId), search_type='id')

	def __str__(self):
		return self.path

	def __repr__(self):
		return f"'{self.path}'"

	def _sanitize(self, path):
		return os.path.relpath(os.path.normpath(os.path.join("/", path)), "/").strip("/")

	@staticmethod
	def parse(client: 'ESXiClient', filepath: str) -> 'DatastoreFile':
		"""
		Convert a path to a `DatastoreFile`

		:param client: The `ESXiClient` to use.
		:param filepath: The file path to resolve. This may be in the form of an absolute path (e.g. `/vmfs/volumes/<id>/path/to/file`) or in the form of a datastore path (e.g. `[datastore] path/to/file`)

		:return: A new `DatastoreFile` object.
		"""
		if filepath.startswith("/"):
			# Absolute path
			# Try to detect the datastore
			PREFIX = "ds://"
			raw_filepath = filepath if filepath.startswith(PREFIX) else PREFIX + filepath
			for ds in client.datastores:
				ds_root_path = ds.path if ds.path.startswith(PREFIX) else PREFIX + ds.path
				if raw_filepath.startswith(ds_root_path):
					return DatastoreFile(ds, raw_filepath[len(ds_root_path):].lstrip("/"))
			raise ValueError(f"Unable to resolve datastore for absolute path {filepath}")
		
		if filepath.startswith("["):
			try:
				match = re.match("\[(" + "|".join([ re.escape(name) for name in client.datastores.names ]) + ")\]\s*(.+)", filepath, flags=re.IGNORECASE)
				datastore_name = match.group(1)
				relative_path = match.group(2).lstrip("/")
				return DatastoreFile(client.datastores.get(datastore_name), relative_path)
			except Exception as e:
				raise ValueError(f"Unable to resolve datastore path {filepath}: {str(e)}")
		raise ValueError(f"Unable to resolve path {filepath}")

