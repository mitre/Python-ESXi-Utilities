from esxi_utils.util import log, parse, exceptions, decorators
from esxi_utils.util.connect.ssh import SSHConnection
from esxi_utils.file.ovf import OvfFile
from esxi_utils.vm.tools.guesttools import GuestTools
from esxi_utils.vm.snapshot import SnapshotList
from esxi_utils.vm.vnc import VNCHandler
from esxi_utils.vm.usb import USBHandler
from esxi_utils.vm.screencapture import ScreenCaptureHandler
from esxi_utils.datastore import Datastore, DatastoreFile
from esxi_utils.vm.hardware.device import VirtualDeviceList
from esxi_utils.vm.hardware.nic import VirtualNICList
from esxi_utils.vm.hardware.disk import VirtualDiskList
from esxi_utils.vm.hardware.cdrom import VirtualCdromList
from esxi_utils.vm.hardware.floppy import VirtualFloppyList
from esxi_utils.vm.hardware.video_card import VirtualVideoCardList
import urllib
import urllib.request
import pyVmomi
import threading
import tempfile
import typing
import time
import ssl
import re
import os

if typing.TYPE_CHECKING:
	from esxi_utils.client import ESXiClient
	from esxi_utils.vm.types.ostype import OSType

class VirtualMachineList:
	"""
	The collection of all virtual machines on the ESXi host.

	:param client: The `ESXiClient` for the ESXi host.
	"""
	def __init__(self, client: 'ESXiClient'):
		self._client = client

	def __iter__(self) -> typing.Iterator['VirtualMachine']:
		from esxi_utils.vm.types.ostype import OSType
		vms = []
		for vim_vm in self._get_vim_vm_objects():
			try:
				guest_id = self._get_guest_id(vim_vm)
				os = OSType.detect(guest_id)
				# skip initializing VMs that don't have configs
				# this prevents errors related to corrupted VMs (e.g. after power outage or bad restarts)
				if not vim_vm.config:
					continue
				vms.append(OSType.map(os)(self._client, vim_vm._moId))
			except pyVmomi.vmodl.fault.ManagedObjectNotFound:
				# When a VM is deleted while iterating over this list, an error will occur
				# This is simply a race condition; we'll skip missing VMs
				continue
		return iter(vms)

	def __getitem__(self, name: str) -> 'VirtualMachine':
		return self.get(name)

	def __contains__(self, name: str):
		return self.exists(name)

	@property
	def items(self) -> typing.List['VirtualMachine']:
		"""
		A list of all items
		"""
		return list(self)

	@decorators.retry_on_error([pyVmomi.vmodl.fault.ManagedObjectNotFound])
	def find(self, name_or_id: str, ostype: typing.Optional['OSType'] = None, search_type: str = "name") -> typing.Union['VirtualMachine', None]:
		"""
		Get a virtual machine by name or ID.
		If multiple VMs match, this will raise a `MultipleVirtualMachinesFoundError` exception.
		
		:param name_or_id: The name or ID of the virtual machine to get. Specify which one you would like to search for with the 'search_type' param.
		:param ostype: An `OSType` enum value for the OS type to use for this VM. If not provided, the OSType value will attempt to be detected.
		:param search_type: Provide "name" to search by name or "id" to search for an ID (default="name").

		:return: A `VirtualMachine` object (or subclass), or `None` if not found.
		"""
		from esxi_utils.vm.types.ostype import OSType
		assert isinstance(name_or_id, (str, int)), "name_or_id must an integer or string"
		assert isinstance(ostype, OSType) or ostype is None, f"ostype must be an OSType value or None, not {ostype}"
		st = search_type.lower().strip()

		matching = [ 
			result["object"] for result in self._query_vm_properties(["name"]) 
			if (st == 'id' and str(result["object"]).strip("'\"").split(":")[-1] == str(name_or_id))
			or (st != 'id' and result["properties"]["name"] == str(name_or_id))
		]
		if len(matching) == 0:
			return None
		if len(matching) > 1:
			raise exceptions.MultipleVirtualMachinesFoundError(name_or_id)

		vim_vm = matching[0]
		if not ostype:
			ostype = OSType.detect(self._get_guest_id(vim_vm))
		return OSType.map(ostype)(self._client, vim_vm._moId)

	def get(self, name_or_id: str, ostype: typing.Optional['OSType'] = None, search_type: str = "name") -> 'VirtualMachine':
		"""
		Get a virtual machine by name or ID and raise an exception if not found.
		If multiple VMs match, this will raise a `MultipleVirtualMachinesFoundError` exception.

		:param name_or_id: The name or ID of the virtual machine to get. Specify which one you would like to search for with the 'search_type' param.
		:param ostype: An `OSType` enum value for the OS type to use for this VM. If not provided, the OSType value will attempt to be detected.
		:param search_type: Provide "name" to search by name or "id" to search for an ID (default="name").

		:return: A `VirtualMachine` object (or subclass)
		"""
		vm = self.find(name_or_id=name_or_id, ostype=ostype, search_type=search_type)
		if vm is None:
			raise exceptions.VirtualMachineNotFoundError(name_or_id)
		return vm
	
	@property
	def names(self) -> typing.List[str]:
		"""
		List the names of all VMs.

		:return: A list of the the VM names.
		"""
		return [ result["properties"]["name"] for result in self._query_vm_properties(["name"]) ]

	def exists(self, name: str) -> bool:
		"""
		Returns whether or not the given VM (by name) exists.

		:return: A boolean whether or not the VM exists.
		"""
		return name in self.names

	def create(
		self, 
		name: str, 
		datastore: typing.Union[str, 'Datastore'], 
		vcpus: int = 1, 
		memory: typing.Union[str, int] = "1GB", 
		guestid: str = "otherGuest",
		version: typing.Optional[str] = None,
		folder_name: typing.Optional[str] = None,
		video_card_auto_detect: typing.Optional[bool] = None,
		uefi_boot: typing.Optional[bool] = None,
	) -> 'VirtualMachine':
		"""
		Create a pre-configured VM.

		:param name: 
			The name of the new VM.
		:param datastore: 
			The datastore where the VM should be created. This can be provided as a string (the name of the datastore) or as a `Datastore` object.
		:param vcpus: 
			The number of vCPUs to assign to this VM. Must be greater or equal to 1.
		:param memory: 
			A string or integer representing the amount of memory to assign to this VM.
			If this is an integer, this represents a size in MB.
			If this is a string, the string is expected to take the form <number><unit>, where <unit> is one of KB, MB, or GB (e.g. 8GB).
		:param guestid: 
			Short guest operating system identifier (See: https://developer.vmware.com/apis/358/vsphere/doc/vim.vm.GuestOsDescriptor.GuestOsIdentifier.html)
		:param version:
			The version string for this virtual machine (e.g. ``vmx-10``). If ``None``, the default version for the ESXi host will be used.
		:param folder_name:
			The folder to contain the new VM. The default is the 'root' VMs folder (if the value 'None' is provided)
			Will create a new folder if one is not found with a matching name.
			Will throw an esxi_utils 'MultipleFoldersFoundError' exception if more than one folder is found with the given name.
		:param uefi_boot:
			When set to 'True' this VM will be created to emulate secure boot mode (UEFI) instead of BIOS (legacy) boot mode (BIOS is default).

		:return: A `VirtualMachine` object (or subtype) for the new VM.
		"""
		assert isinstance(name, str), "name must be a string"
		assert isinstance(vcpus, int) and vcpus >= 1, "vcpus must be an integer greater than 1"
		assert isinstance(memory, (int, str)), "memory must be a string or integer"
		assert isinstance(guestid, str), "guestid must be a string"
		assert (isinstance(version, str) and re.match(r"^vmx\-\d+$", version)) or version is None, "version must be a string in the form \"vmx-[0-9]+\", or None"

		if isinstance(datastore, str):
			datastore = self._client.datastores.get(datastore)
		if not isinstance(datastore, Datastore):
			raise TypeError(f"datastore is not a valid Datastore object")

		if isinstance(memory, str):
			memory = parse.size_string(memory, unit="MB")

		# Create spec
		config = pyVmomi.vim.vm.ConfigSpec()
		config.memoryMB = int(memory)
		config.guestId = guestid
		config.name = name
		config.numCPUs = vcpus
		config.version = version if version else None
		files = pyVmomi.vim.vm.FileInfo()
		files.vmPathName = f"[{datastore.name}]" # Root folder of the datastore
		config.files = files

		#TODO add options to set this and other config options.
		config.changeTrackingEnabled = False

		if uefi_boot:
			# Set the firmware to UEFI
			config.firmware = 'efi'  # Explicitly set the firmware type to EFI
			boot_options = pyVmomi.vim.vm.BootOptions()
			boot_options.efiSecureBootEnabled = True # Set the boot option to EFI
			config.bootOptions = boot_options

		scsi_ctr = pyVmomi.vim.vm.device.VirtualDeviceSpec(
			operation=pyVmomi.vim.vm.device.VirtualDeviceSpec.Operation.add,
			device=pyVmomi.vim.vm.device.VirtualLsiLogicSASController(
				sharedBus=pyVmomi.vim.vm.device.VirtualSCSIController.Sharing.noSharing
			)
		)
		config.deviceChange = [ scsi_ctr ]

		if video_card_auto_detect:
			video_card = pyVmomi.vim.vm.device.VirtualDeviceSpec(
				operation=pyVmomi.vim.vm.device.VirtualDeviceSpec.Operation.add,
				device=pyVmomi.vim.vm.device.VirtualVideoCard()
			)

			if video_card_auto_detect:
				video_card.device.useAutoDetect = True
			
			# this doesn't seem to work (at least at creation time)
			# if video_card_mem_kb:
			# 	video_card.device.graphicsMemorySizeInKB = video_card_mem_kb

			config.deviceChange.append(video_card)

		# Add VM
		destination_host = self._client._host_system
		root_folder = datastore._datacenter.vmFolder
		folder = VirtualMachineList._get_folder(root_folder, folder_name)
		
		vim_vm = self._client._wait_for_task(folder.CreateVM_Task(
			config,
			pool=destination_host.parent.resourcePool,
			host=destination_host
		))
		return self.get(str(vim_vm._moId), search_type='id')

	@staticmethod
	def _search_for_folder(current_folder, folder_to_find: str) -> list:
		"""
		Traverses the 'root' VM folder for a folder with a given name.
		This function is called recursively to decend into nested folders.

		:param current_folder:
			the folder entity that is currently being searched (or the 'root' vm folder)
		:param folder_to_find:
			the name (str) of the folder being searched for
		:return:
			a list of all found folder entities with a name matching the given parameter 'folder_to_find'
		"""
		found_entities = []
		# childEntity is an array of childTypes
		# the root folder can contain: 'Folder', 'VirtualMachine', and 'VirtualApp' entities
		for e in current_folder.childEntity:
			# check that the matching entity can contain a folder as a child (and therefore IS a folder)
			childTypeArray = getattr(e, 'childType', None)
			if childTypeArray is None:
				# this is not a folder, but we can keep looking for a folder with the same name
				continue
			if 'Folder' in childTypeArray:
				# this entity can contain a child folder and is likely a folder itself
				if str(e.name).strip().lower() == folder_to_find:
					found_entities.append(e)
					continue
				# else search the subfolders of this folder
				new_entities = VirtualMachineList._search_for_folder(e, folder_to_find)
				if len(new_entities) > 0:
					found_entities.extend(new_entities)
		# end for loop: entity in childEntity(s)
		return found_entities
	
	@staticmethod
	def _get_folder(root_folder, folder_name: str):
		"""
		Attempts to retrieve a folder with the given 'folder_name' param from the 'root_folder'.
		Will create a new folder if one is not found.

		:param root_folder:
			The 'root' or 'base' folder in which VMs are contained in ESXi. Sometimes the folder name itself is simply 'vm'.
		:param folder_name:
			The folder to contain the new VM. The default is the 'root' VMs folder (if the value 'None' is provided)
			Will create a new folder if one is not found with a matching name.
			Will throw an esxi_utils 'MultipleFoldersFoundError' exception if more than one folder is found with the given name.
		:return:
			An ESXi folder object entity in which to place VMs under.
		"""
		if not folder_name:
			return root_folder
		folder = root_folder
		
		# check that the root folder supports child folders
		childTypeArray = getattr(root_folder, 'childType', None)
		if childTypeArray is None or 'Folder' not in childTypeArray:
			log.debug(f'The root VM folder does not support child folders. Creating VM in root VM folder instead.')
			return root_folder

		log.debug(f'Searching for folder name: {folder_name}')
		matching_folders = VirtualMachineList._search_for_folder(root_folder, folder_name.strip().lower())

		if len(matching_folders) <= 0:
			log.debug(f'No matching folder found. Creating new folder with name: {folder_name}')
			# a race condition can exist where multiple threads try to create the folder at the same time (or start to)
			# this catches that issue
			try:
				folder = root_folder.CreateFolder(name=folder_name)
			except Exception as e:
				if "vim.fault.DuplicateName" not in str(e):
					raise e
				time.sleep(5)
				log.debug('Failed to create a new folder (did it just get created in parallel?) ... Searching again...')
				log.debug(f'Searching for folder name: {folder_name}')
				matching_folders = VirtualMachineList._search_for_folder(root_folder, folder_name.strip().lower())

		if len(matching_folders) > 1:
			raise exceptions.MultipleFoldersFoundError(matching_folders)
		
		# If we fail to create a folder this value can be 0 (in that case we grab the duplicate folder name)
		if len(matching_folders) == 1:
			folder = matching_folders[0]

		log.debug(f'VM will upload in folder name: {folder.name}')
		return folder

	def upload(self, file: typing.Union[str, OvfFile], datastore: typing.Union[str, 'Datastore'], name: typing.Optional[str] = None, network_mappings: typing.Optional[typing.Dict[str, str]] = None, folder_name: typing.Optional[str] = None) -> 'VirtualMachine':
		"""
		Uploads a local OVF or OVA file to the provided datastore as a new VM.

		:param file: A path to a .ovf/.ova file (string), or an `OvfFile` object.
		:param datastore: The datastore where the VM should be created. This can be provided as a string (the name of the datastore) or as a `Datastore` object.
		:param name: The name of the new VM. If `None`, the name is based on the name defined in the OVF/OVA.
		:param network_mappings: A dictionary of network mappings. If `None` or a mapping for a network isn't provided, the network will be mapped to itself.
		:param folder_name:
			The folder to contain the new VM. The default is the 'root' VMs folder (if the value 'None' is provided)
			Will create a new folder if one is not found with a matching name.
			Will throw an esxi_utils 'MultipleFoldersFoundError' exception if more than one folder is found with the given name.
		
		:return: A `virtualmachine.VirtualMachine` object for the new VM.
		"""
		if isinstance(file, str):
			file = OvfFile(file)
		if not isinstance(file, OvfFile):
			raise TypeError(f"file is not a valid OvfFile object")

		if isinstance(datastore, str):
			datastore = self._client.datastores.get(datastore)
		if not isinstance(datastore, Datastore):
			raise TypeError(f"datastore is not a valid Datastore object")

		if name is None:
			name = file.vmname
		if not isinstance(name, str):
			raise TypeError(f"name must be a string")

		if network_mappings is None:
			network_mappings = dict()
		if not isinstance(network_mappings, dict):
			raise TypeError(f"network_mappings must be a dict")

		log.info(f"Uploading VM to datastore \"{datastore.name}\" from file {file.path} (name={name})...")
		file.validate()

		if self.exists(name):
			raise exceptions.VirtualMachineExistsError(name)

		# Check datastore space
		available_space = datastore.freespace(unit="GB")
		required_space = file.required_storage(unit="GB")
		log.debug(f"Datastore {datastore.name} has {available_space}GB available (required: {required_space}GB)...")
		if available_space < required_space:
			raise exceptions.DatastoreSpaceError(datastore, f"{required_space}GB", f"{available_space}GB")

		# Create network mappings
		mappings = []
		for network_name in file.networks:
			mapped_to = network_mappings.get(network_name, network_name)
			try:
				network_obj = self._client._get_network_object_from_host_system(mapped_to)
			except Exception as e:
				raise exceptions.OvfImportError(file.path, datastore.name, name, str(f"unable to map network {network_name} to {mapped_to}. Reason: {e}"))
			mappings.append(pyVmomi.vim.OvfManager.NetworkMapping(name=network_name, network=network_obj))

		# Create import spec
		log.debug(f"Creating import spec...")
		resource_pool = self._client._host_system.parent.resourcePool
		import_spec = self._client._service_instance.content.ovfManager.CreateImportSpec(
			ovfDescriptor=file.descriptor.xml(pretty_print=True, xml_declaration=True),
			resourcePool=resource_pool,
			datastore=datastore._datastore,
			cisp=pyVmomi.vim.OvfManager.CreateImportSpecParams(
				entityName=name,
				networkMapping=mappings,
			)
		)
		if len(import_spec.error) != 0:
			raise exceptions.OvfImportError(file.path, datastore.name, name, str(import_spec.error))
		for warning in import_spec.warning:
			log.warning(f"Warning while importing VM from {file.path}: {warning.msg}")

		class LeaseProgressUpdater(threading.Thread):
			def __init__(self, lease, total_bytes):
				threading.Thread.__init__(self)
				self.lease = lease
				self.bytes_read = 0
				self.total_bytes = total_bytes
				self._run = True
				self.error = None

			def done(self):
				self._run = False

			def run(self):
				while self._run:
					try:
						if self.lease.state == pyVmomi.vim.HttpNfcLease.State.done:
							return
						progress = int(min(self.bytes_read / self.total_bytes * 100, 99))
						self.lease.HttpNfcLeaseProgress(progress)
						time.sleep(1)
					except Exception as e:
						self.error = e
						self._run = False
						return

		class LeasedFileReader:
			def __init__(self, file, updater):
				self.file = file
				self.updater = updater

			def read(self, n=-1):
				chunk = self.file.read(n)
				updater.bytes_read += len(chunk)
				return chunk
				
		root_folder = datastore._datacenter.vmFolder
		folder = VirtualMachineList._get_folder(root_folder, folder_name)
		
		log.debug(f"Creating import lease...")
		lease = resource_pool.ImportVApp(
			spec=import_spec.importSpec,
			folder=folder,
			host=self._client._host_system
		)

		# Wait for ready
		log.debug(f"Waiting for lease to be ready...")
		for i in range(10):
			if lease.state != pyVmomi.vim.HttpNfcLease.State.initializing:
				break
			time.sleep(2)
			log.debug(f"Waiting for lease to be ready (retry={i+1})...")
		else:
			lease.HttpNfcLeaseAbort()
			raise exceptions.OvfImportError(file.path, datastore.name, name, "Failed to wait for lease initalization")

		if lease.state == pyVmomi.vim.HttpNfcLease.State.error:
			lease.HttpNfcLeaseAbort()
			raise exceptions.OvfImportError(file.path, datastore.name, name, str(lease.error))

		if lease.state != pyVmomi.vim.HttpNfcLease.State.ready:
			lease.HttpNfcLeaseAbort()
			raise exceptions.OvfImportError(file.path, datastore.name, name, "unknown export state")

		# Get the total size of the files to upload
		# We also need to map the local filenames to the uploaded filenames
		total_bytes = 0
		key_to_filename = {}
		for item in import_spec.fileItem:
			total_bytes += item.size
			key = os.path.basename(item.deviceId)
			if key in key_to_filename:
				raise exceptions.OvfImportError(file.path, datastore.name, name, f"import key {key} already mapped. File items: {str(import_spec.fileItem)}")
			key_to_filename[key] = item.path
			log.debug(f"Preparing to upload file {item.path} (key={key}, size={item.size})...")
		updater = LeaseProgressUpdater(lease, total_bytes)

		vm_id = lease.info.entity._moId
		try:
			# Start uploading
			updater.start()
			ctx = ssl.create_default_context()
			ctx.check_hostname = False
			ctx.verify_mode = ssl.CERT_NONE
			for device_url in lease.info.deviceUrl:
				name = device_url.targetId
				if name is None:
					continue
				url = device_url.url.replace('*', self._client.hostname)
				key = os.path.basename(device_url.importKey)
				if key not in key_to_filename:
					raise exceptions.OvfImportError(file.path, datastore.name, name, f"Failed to upload {file.path}: import key {key} not found")
				filename = key_to_filename[key]
				del key_to_filename[key]
				log.debug(f"Uploading file {item.path} (key={key})...")
				with file.open(filename, mode="rb") as f:
					reader = LeasedFileReader(f, updater)

					if device_url.disk:
						method = 'POST'
						headers = {}
					else:
						method = 'PUT'
						headers = {'Overwrite':'t'}

					with urllib.request.urlopen(urllib.request.Request(url, data=reader, method=method, headers=headers), context=ctx) as response:
						response_content = response.read()
						if response.status != 201:
							raise exceptions.OvfImportError(file.path, datastore.name, name, f"Error while writing file (status {response.status}): {response_content}")
				log.debug(f"Uploaded file {item.path} (key={key})...")
			lease.HttpNfcLeaseProgress(100)
			lease.HttpNfcLeaseComplete()
		except Exception as e:
			lease.HttpNfcLeaseAbort()
			raise e
		finally:
			updater.done()

		# We will attempt to get the new VM several times to account for possible delays in the VM being registered
		for _ in range(5):
			vm = self.find(str(vm_id), search_type='id')
			if vm is not None:
				return vm
			time.sleep(2)
		raise exceptions.OvfImportError(file.path, datastore.name, name, "failed to get virtual machine object after deployment")

	@decorators.retry_on_error([pyVmomi.vmodl.fault.ManagedObjectNotFound])
	def _query_vm_properties(self, properties):
		"""
		Retrieve a set of a properties for all VMs. This performs much quicker than manually getting the properties from `pyVmomi.vim.VirtualMachine` objects.

		:param: A list of strings indicating the properties to retrieve.

		:return: A list of results
		"""
		assert isinstance(properties, list)

		prop_spec = pyVmomi.vmodl.query.PropertyCollector.PropertySpec(type=pyVmomi.vim.VirtualMachine, all=False)
		prop_spec.pathSet = properties

		obj_spec = [ pyVmomi.vmodl.query.PropertyCollector.ObjectSpec(obj=vm) for vm in self._get_vim_vm_objects() ] 
		filter_spec = pyVmomi.vmodl.query.PropertyCollector.FilterSpec(objectSet=obj_spec, propSet=[prop_spec])
		
		collector = self._client._service_instance.RetrieveContent().propertyCollector
		retrieve_result = collector.RetrievePropertiesEx([ filter_spec ], pyVmomi.vmodl.query.PropertyCollector.RetrieveOptions())

		results = []
		while len(retrieve_result.objects):
			results.extend([ { "object": obj.obj, "properties": { propSet.name: propSet.val for propSet in obj.propSet } } for obj in retrieve_result.objects ])
			if retrieve_result.token is None:
				break
			retrieve_result = collector.ContinueRetrievePropertiesEx(token=retrieve_result.token)

		return results

	def _get_vim_vm_objects(self) -> typing.List[typing.Any]:
		"""
		Get all pyVmomi VM objects.

		:return: A list of all pyVmomi VM objects.
		"""
		return [ vm for vm in self._client._get_vim_objects(pyVmomi.vim.VirtualMachine) ]

	def _get_guest_id(self, vim_vm) -> typing.Union[str, None]:
		"""
		Attempt to get the guest ID for a pyVmomi VM object.

		:param vim_vm: The pyVmomi VM object.

		:return: The detected guest ID, or ``None`` if a guest ID could not be detected.
		"""
		# Sometimes a VM will not report a config or guestId
		# To handle these cases, we'll retry a couple times
		guest_id = None
		for retry in range(3):
			if retry > 0:
				time.sleep(0.5)
			if not hasattr(vim_vm, "config") or vim_vm.config is None or not hasattr(vim_vm.config, "guestId"):
				continue
			guest_id = vim_vm.config.guestId
			if guest_id:
				return guest_id
		return None

	def __str__(self):
		return f"<{type(self).__name__} for {self._client.hostname} ({len(self.items)} virtual machines)>"

	def __repr__(self):
		return str(self)


class VirtualMachine:
	"""
	A virtual machine on an ESXi host. 
	"""
	def __init__(self, client: 'ESXiClient', id: typing.Union[int, str]):
		self._client = client
		self._id = str(id)

	@property
	def id(self) -> str:
		"""
		The ID of this VM.
		"""
		return self._id

	@property
	def name(self) -> str:
		"""
		The name of this VM.
		"""
		return self._vim_vm.name

	@property
	def ssh(self) -> typing.Type['SSHConnection']:
		"""
		A generic SSH connection object for establishing a remote connection to this VM.
		"""
		return SSHConnection

	@property
	def devices(self) -> 'VirtualDeviceList':
		"""
		Get all hardware devices for this VM.
		"""
		return VirtualDeviceList(self)

	@property
	def nics(self) -> 'VirtualNICList':
		"""
		The NICs assigned to this VM.
		"""
		return VirtualNICList(self)

	@property
	def disks(self) -> 'VirtualDiskList':
		"""
		The disks assigned to this VM.
		"""
		return VirtualDiskList(self)
	
	@property
	def cdroms(self) -> 'VirtualCdromList':
		"""
		The CD-ROMs assigned to this VM.
		"""
		return VirtualCdromList(self)

	@property
	def floppies(self) -> 'VirtualFloppyList':
		"""
		The floppy disks assigned to this VM.
		"""
		return VirtualFloppyList(self)
	
	@property
	def video_cards(self) -> 'VirtualVideoCardList':
		"""
		The video cards assigned to this VM.
		"""
		return VirtualVideoCardList(self)

	@property
	def snapshots(self) -> 'SnapshotList':
		"""
		Get the snapshot handler for this VM.
		"""
		return SnapshotList(self)

	@property
	def tools(self) -> 'GuestTools':
		"""
		Get the VMware Tools object for this VM.
		"""
		return GuestTools(self)

	@property
	def vnc(self) -> 'VNCHandler':
		"""
		The VNC handler for this VM.
		(Deprecated, will not work in ESXi >= 7.0)
		(Use usb and screen_capture functions instead)
		"""
		return VNCHandler(self)
	
	@property
	def usb(self) -> 'USBHandler':
		"""
		The USB scan code handler for this VM.
		(ESXi >= 6.7)
		"""
		return USBHandler(self)
	
	@property
	def screen_capture(self) -> 'ScreenCaptureHandler':
		"""
		The screen capture handler for this VM.
		(ESXi >= 6.7)
		"""
		return ScreenCaptureHandler(self)

	@property
	def uuid(self) -> str:
		"""
		The UUID of this VM.
		"""
		return self._vim_vm.summary.config.uuid

	@property
	def filepath(self) -> 'DatastoreFile':
		"""
		The filepath to the VM's vmx file on the VM's datastore as a `DatastoreFile` object.
		"""
		return DatastoreFile.parse(self._client, self._vim_vm.config.files.vmPathName)

	@property
	def datastore(self) -> 'Datastore':
		"""
		The datastore containing the VM files.
		"""
		return self.filepath.datastore

	@property
	def files(self) -> typing.List['DatastoreFile']:
		"""
		All files (and metadata) stored in this VM's folder as a list of `DatastoreFile` objects.
		"""
		return self.folder.ls(recursive=True)

	@property
	def folder(self) -> 'DatastoreFile':
		"""
		The path to the VM's folder (the folder storing the VM's VMX file) on the VM's datastore, as a `DatastoreFile` object
		"""
		return self.filepath.parent

	@property
	def powered_on(self) -> bool:
		"""
		Whether the VM is currently powered on.
		"""
		return self._vim_vm.runtime.powerState == pyVmomi.vim.VirtualMachine.PowerState.poweredOn

	@property
	def powered_off(self) -> bool:
		"""
		Whether the VM is currently powered off.
		"""
		return self._vim_vm.runtime.powerState == pyVmomi.vim.VirtualMachine.PowerState.poweredOff

	@property
	def vcpus(self) -> int:
		"""
		The number of VCPUs on this VM.
		"""
		return self._vim_vm.summary.config.numCpu

	@vcpus.setter
	def vcpus(self, num_cpus: int):
		"""
		Sets the number of vCPUs for this VM. The VM must be powered off.

		:param num_cpus: The number of vCPUs to assign to this VM. Must be greater or equal to 1.
		"""
		assert isinstance(num_cpus, int) and num_cpus >= 1, "num_cpus must be an integer greater or equal to 1"
		spec = pyVmomi.vim.vm.ConfigSpec()
		spec.numCPUs = num_cpus
		self._client._wait_for_task(
			self._vim_vm.ReconfigVM_Task(spec=spec)
		)

	@property
	def vcpu_cores_per_socket(self) -> int:
		"""
		The number of cores per socket on this VM.
		"""
		return self._vim_vm.config.hardware.numCoresPerSocket

	@vcpu_cores_per_socket.setter
	def vcpu_cores_per_socket(self, cores: int):
		"""
		Sets the number of cores per socket for this VM. The VM must be powered off.

		:param cores: The number of cores per socket to assign to this VM. Must be divisor of the number of VCPUs (up to the number of cores on the host).
		"""
		# We need to manually enforce the number of cores since ESXi will allow you to set any value,
		# but setting the incorrect value will result in the VM failing to boot
		# The valid options are all the divisors of the number of vcpus, up to and include the number of cores
		# on the ESXi host
		HOST_CORES = self._client._host_system.hardware.cpuInfo.numCpuCores
		options = [ n for n in range(1, min(self.vcpus, HOST_CORES)+1) if self.vcpus % n == 0 ]
		assert cores in options, f"invalid value for number of cores per socket. Value must be one of: {', '.join([ str(n) for n in options ])}"

		spec = pyVmomi.vim.vm.ConfigSpec()
		spec.numCoresPerSocket = cores
		self._client._wait_for_task(
			self._vim_vm.ReconfigVM_Task(spec=spec)
		)

	@property
	def memory(self) -> int:
		"""
		The amount of memory in MB for this VM.
		"""
		return self._vim_vm.summary.config.memorySizeMB

	@memory.setter
	def memory(self, memory: typing.Union[int, str]):
		"""
		Sets the amount of memory for this VM. The VM must be powered off.

		:param memory: 
			A string or integer representing the amount of memory to assign to this VM.
			If this is an integer, this represents a size in MB.
			If this is a string, the string is expected to take the form <number><unit>, where <unit> is one of KB, MB, or GB (e.g. 8GB).
		"""
		assert isinstance(memory, (str, int))
		if isinstance(memory, str):
			memory = parse.size_string(memory, unit="MB")
		assert memory >= 1, "memory must be greater or equal to 1"
		spec = pyVmomi.vim.vm.ConfigSpec()
		spec.memoryMB = memory
		self._client._wait_for_task(
			self._vim_vm.ReconfigVM_Task(spec=spec)
		)

	@property
	def guestid(self) -> str:
		"""
		The Guest OS for this VM.
		"""
		return self._vim_vm.summary.config.guestId

	@guestid.setter
	def guestid(self, guestId: str):
		"""
		Set the Guest ID for this VirtualMachine.

		:param guestid: Short guest operating system identifier (See: https://developer.vmware.com/apis/358/vsphere/doc/vim.vm.GuestOsDescriptor.GuestOsIdentifier.html)
		"""
		spec = pyVmomi.vim.vm.ConfigSpec()
		spec.guestId = guestId
		self._client._wait_for_task(
			self._vim_vm.ReconfigVM_Task(spec=spec)
		)

	@property
	def ostype(self) -> 'OSType':
		"""
		The `OSType` for this Virtual Machine.
		"""
		from esxi_utils.vm.types.ostype import OSType
		return OSType.Unknown

	def used_space(self, unit: str = "KB") -> int:
		"""
		Get the amount of space used on disk by this VM and its associated files.

		:param unit: The unit of measurement to use (one of: B, KB, MB, GB).

		:return: The disk usage.
		"""
		conversion_factors = { "B": 1, "KB": 1024, "MB": 1024*1024, "GB": 1024*1024*1024 }
		assert unit in conversion_factors
		path = os.path.dirname(self.filepath.relpath)
		size = 0
		
		for data_file in self.files:
			size += data_file.stat["size"] / conversion_factors[unit]

		return int(size)

	def size(self, unit: str = "KB") -> int:
		"""
		Get the total storage space occupied by the virtual machine across all datastores, that is not shared with any other virtual machine.

		:param unit: The unit of measurement to use (one of: B, KB, MB, GB).

		:return: The total storage space occupied by the virtual machine.
		"""
		conversion_factors = { "B": 1, "KB": 1024, "MB": 1024*1024, "GB": 1024*1024*1024 }
		assert unit in conversion_factors
		b = self._vim_vm.summary.storage.unshared
		try:
			t = self._vim_vm.summary.storage.timestamp
			self._vim_vm.RefreshStorageInfo()
			timeout_time = 30 # seconds
			start_time = time.time()
			while self._vim_vm.summary.storage.timestamp == t:
				time.sleep(1)
				if time.time() >= start_time + timeout_time:
					raise Exception('Timeout waiting for RefreshStorageInfo in size()')
			b = self._vim_vm.summary.storage.unshared
		except Exception:
			pass
		return int(b / conversion_factors[unit])

	@property
	def vmx(self) -> typing.Dict[str, str]:
		"""
		Get the content of the VM's VMX file.

		:return: The dictionary representation of the VM's VMX file
		"""
		raw = self.filepath.read()
		vmx = {}
		for line in raw.strip().split("\n"):
			line_split = line.split("=")
			line_key = line_split[0].strip()
			line_value = line_split[1].strip().strip('"')
			vmx[line_key] = line_value
		return vmx

	@vmx.setter
	def vmx(self, vmx_obj: typing.Dict[str, str]):
		"""
		Updates the contents of the VM's VMX file.

		:param new_content: The new content of the VMX file (as an dictionary mapping key to value).
		"""
		assert isinstance(vmx_obj, dict), "vmx_obj must be a dictionary"
		lines = []
		for key, value in vmx_obj.items():
			lines.append(f"{key} = \"{value}\"")
		content = '\n'.join(lines)
		self.filepath.write(content)
		
	def wait(self, powered_on: bool = True, retries: int = 60, delay: int = 2) -> bool:
		"""
		Wait for the power state of the VM to be the desired state (powered on or powered off).

		:param powered_on: If `True`, wait for the power state to be "ON", otherwise wait for the power state to be "OFF".
		:param retries: How many times to retry before exiting.
		:param delay: How long to pause between retries (in seconds).

		:return: A boolean whether or not the state was reached in the allotted amount of retries.
		"""
		attempts = 0
		for i in range(retries):
			try:
				if powered_on == self.powered_on:
					return True
			except Exception as e:
				if attempts == 1:
					raise e
				else:
					attempts += 1
			time.sleep(delay)
		return False

	def assert_powered_off(self):
		"""
		Raises an exception if the VM is not currently powered off.
		"""
		if self.powered_on:
			raise exceptions.VirtualMachineNotPoweredOffError(self.name)

	def assert_powered_on(self):
		"""
		Raises an exception if the VM is not currently powered on.
		"""
		if not self.powered_on:
			raise exceptions.VirtualMachineNotPoweredOnError(self.name)

	def power_on(self, idempotent: bool = False):
		"""
		Powers on the VM.

		:param idempotent: If `True` and the VM is already powered on, this will do nothing rather than throwing an error.
		"""
		if self.powered_on and not idempotent:
			raise exceptions.VirtualMachineAlreadyPoweredOnError(self.name)
		elif self.powered_on:
			return
		self._client._wait_for_task(self._vim_vm.PowerOnVM_Task(host=self._client._host_system))

	def power_off(self, idempotent: bool = False):
		"""
		Powers off the VM.

		:param idempotent: If `True` and the VM is already powered on, this will do nothing rather than throwing an error.
		"""
		if self.powered_off and not idempotent:
			raise exceptions.VirtualMachineAlreadyPoweredOffError(self.name)
		elif self.powered_off:
			return
		self._client._wait_for_task(self._vim_vm.PowerOffVM_Task())

	def reset(self):
		"""
		Perform an ESXi reset of the VM (hard reboot).
		"""
		self._client._wait_for_task(self._vim_vm.ResetVM_Task())

	def reload(self):
		"""
		Reloads the VM. This refreshes the VM to recognize any changes made to the local files (i.e. the VMX file).
		"""
		self._vim_vm.Reload()

	@decorators.retry_on_error([pyVmomi.vmodl.fault.ManagedObjectNotFound])
	def remove(self):
		"""
		Removes the VM from the server.
		"""

		def _remove_vm():
			self.assert_powered_off()
			try:
				return self._vim_vm.Destroy_Task()
			except pyVmomi.vmodl.fault.ManagedObjectNotFound as e:
				return None

		def _get_state(task):
			try:
				return task.info.state
			except pyVmomi.vmodl.fault.ManagedObjectNotFound as e:
				return pyVmomi.vim.TaskInfo.State.success

		def _get_msg(task):
			e = task.info.error if task.info.error else None
			if e:
				return str(e).lower()
			else:
				return str(task.info).lower()		

		remove_task = _remove_vm()
		retries = 0
		max_retries = 25
		start_time = time.time()
		timeout = 600

		while remove_task and _get_state(remove_task) != pyVmomi.vim.TaskInfo.State.success:
			if _get_state(remove_task) == pyVmomi.vim.TaskInfo.State.error:
				if 'could not delete change tracking file' in _get_msg(remove_task):
					if retries >= max_retries:
						log.error('Max retries reached with removing vm. Raising exception.')
						raise exceptions.ESXiAPIError(str(remove_task.info))
					log.debug(f'VM removal blocked by change tracking file. Retrying...')
					self.assert_powered_off()
					remove_task = _remove_vm()
					time.sleep(5)
					retries += 1
					continue
			elif _get_state(remove_task) == pyVmomi.vim.TaskInfo.State.running:
				time.sleep(1)
			elif _get_state(remove_task) == pyVmomi.vim.TaskInfo.State.queued and time.time() >= start_time + timeout:
				raise exceptions.ESXiAPIError(f"Operation still queued after {timeout} seconds.")

	def get_world_id(self) -> int:
		"""
		The World ID of the VM. Unlike the VM's standard ID, the World ID is associated only with a running VM and may change when the VM is restarted.

		:return: The VM's World ID.
		"""
		self.assert_powered_on()
		with self._client.ssh() as conn:
			output = conn.esxcli("network vm list")
			for entry in output:
				if entry['Name'] == self.name:
					return entry['WorldID']
			raise exceptions.ESXiShellCommandError(f"esxcli network vm list", f"World ID for VM \"{self.name}\" not found", output)

	def clone(self, new_vm_name: str, datastore: typing.Union[str, 'Datastore', None] = None) -> 'VirtualMachine':
		"""
		Clones the VM to a new VM. Snapshots will be preserved.

		:param new_vm_name: The name of the new VM.
		:param datastore: The datastore to clone the VM to. This can be specified as either the datastore name (string), a `Datastore` object, or `None` to use the same datastore.
		
		:return: A `VirtualMachine` object for the newly created VM.
		"""
		# We need to implement a custom clone function since the Clone task in pyVmomi isn't available on ESXi without vCenter
		log.info(f"Cloning {self.name} to {new_vm_name}...")
		if self._client.vms.exists(new_vm_name):
			raise exceptions.VirtualMachineExistsError(new_vm_name)
		self.assert_powered_off()

		datastore = self.datastore if datastore is None else self._client.datastores.resolve(datastore)
		srcdir = self.filepath.parent

		# Create destination directory
		i = 1
		dstdir = datastore.root / new_vm_name
		while dstdir.exists:
			dstdir = datastore.root / f"{new_vm_name}_{i}"
			i += 1

		try:
			# First copy everything
			srcdir.copy(to=dstdir)

			# Remove unnecessary files
			files_to_remove =  [ file for file in dstdir.files if file.filename.lower().endswith(".log") or file.filename.lower().endswith(".vswp") ]
			for file in files_to_remove:
				log.debug(f"[Clone {self.name}] Removing \"{file.path}\"")
				file.remove()

			# Modify VMX
			vmxpath = dstdir / self.filepath.filename
			log.debug(f"[Clone {self.name}] Updating VMX at \"{vmxpath.path}\"")
			contents = vmxpath.read()
			lines_to_remove = [
				"displayName",
				"uuid.bios",
				"uuid.location",
				"sched.swap.derivedName",
				"ethernet[0-9]+.generatedAddress",
				"ethernet[0-9]+.addressType"
			]
			newlines = []
			for line in contents.split("\n"):
				remove_line = any([ re.search(line_to_remove, line, flags=re.IGNORECASE) for line_to_remove in lines_to_remove ]) # Remove line if any match
				if not remove_line:
					newlines.append(line)
				else:
					log.debug(f"[Clone {self.name}] Removing line from VMX: {line}")
			contents = "\n".join(newlines)
			vmxpath.write(contents)
			
			# Update VMDKs
			# We want to hole-punch the VMDKs wherever possible to allow ESXi to display the correct space usage
			# log.info(f"[Clone {self.name}] Updating VMDKs")
			# self._client.exec_commands({ 
			# 	"cmd": r"find . -name '*.vmdk' -exec vmkfstools -K {} \;", 
			# 	"timeout": 0, 
			# 	"cwd": dst 
			# })

			# Register the destination as a new VM
			log.debug(f"[Clone {self.name}] Registering new VM")
			return vmxpath.register_vm(name=new_vm_name)
		except Exception as e:
			dstdir.remove()
			raise e
	
	def export(self, path: str = ".", format: str = "ovf", hash_type: str = "sha1", include_image_files: bool = False, include_nvram: bool = False) -> OvfFile:
		"""
		Export this virtual machine to an OVF/OVA file. 
		
		Note: The export progress shown on the ESXi UI may not reflect the actual progress (due to limitations with determining the actual download size).

		:param path: The directory to export to. Defaults to the current directory.
		:param format: The export format. One of: ovf, ova. Default to 'ovf'
		:param hash_type: Algorithm to use for generating manifest hashes. One of: sha1, sha256, sha512. Defaults to 'sha1'
		:param include_image_files: Whether to include image files (e.g. .iso files)
		:param include_nvram: Whether to include the nvram file.
		
		:return: A `VirtualApplianceFile` object for the exported VM (based on export format).
		"""
		self.assert_powered_off()
		if format not in ["ovf", "ova"]:
			raise ValueError(f"VM format must be either 'ovf' or 'ova'")

		path = os.path.abspath(path)
		if not os.path.isdir(path):
			raise NotADirectoryError(f"{path} is not a valid directory")
		
		output_target = os.path.join(path, self.name + "." + format)
		if os.path.exists(output_target):
			raise FileExistsError(f"{output_target} already exists")
		
		class LeaseProgressUpdater(threading.Thread):
			def __init__(self, lease):
				threading.Thread.__init__(self)
				self.lease = lease
				self.progress = 0
				self._run = True
				self.error = None

			def done(self):
				self._run = False

			def run(self):
				while self._run:
					try:
						if self.lease.state == pyVmomi.vim.HttpNfcLease.State.done:
							return
						self.lease.HttpNfcLeaseProgress(int(self.progress))
						time.sleep(5)
					except Exception as e:
						self.error = e
						self._run = False
						return


		lease = self._vim_vm.ExportVm()

		# Wait for ready
		for _ in range(10):
			if lease.state != pyVmomi.vim.HttpNfcLease.State.initializing:
				break
			time.sleep(2)
		else:
			lease.HttpNfcLeaseAbort()
			raise exceptions.VirtualMachineExportError(self.name, output_target, "Failed to wait for lease initalization")

		if lease.state == pyVmomi.vim.HttpNfcLease.State.error:
			lease.HttpNfcLeaseAbort()
			raise exceptions.VirtualMachineExportError(self.name, output_target, str(lease.state.error))

		if lease.state != pyVmomi.vim.HttpNfcLease.State.ready:
			lease.HttpNfcLeaseAbort()
			raise exceptions.VirtualMachineExportError(self.name, output_target, "unknown export state")

		updater = LeaseProgressUpdater(lease)
		with tempfile.TemporaryDirectory(prefix="vmexport") as temp:
			try:
				ctx = ssl.create_default_context()
				ctx.check_hostname = False
				ctx.verify_mode = ssl.CERT_NONE

				# Prepare download
				total_bytes_read = 0
				total_bytes = self.size(unit="B")

				# start VM file size checking/refreshing
				if total_bytes <= 0:
					log.info("VM file size evaluated to zero. Refreshing storage info...")
					# It is likely that you are on a vCenter that is slow
					# Refresh the memory storage info and try again
					self._vim_vm.RefreshStorageInfo()
					time.sleep(10)
					total_bytes = self.size(unit="B")
					if total_bytes <= 0:
						timeout_time = 60 * 6
						refresh_again_time = timeout_time / 2
						refreshed = False
						log.debug(f'Looping to wait for VM file size to update. Timeout at: {timeout_time / 60} minutes.')
						start_time = time.time()
						while total_bytes <= 0:
							now = time.time()
							log.debug(f'VM file size still zero. Elapsed time: {(now - start_time) / 60} minutes.')
							if now >= start_time + timeout_time:
								raise exceptions.VirtualMachineExportError(self.name, output_target, f"Error while exporting file: total bytes of VM evaluated to 0! Timeout waiting for Refresh!")
							elif not refreshed and now >= start_time + refresh_again_time:
								log.info("VM file size still evaluating to zero. Attempting final refresh...")
								self._vim_vm.RefreshStorageInfo()
								refreshed = True
							time.sleep(30)
							total_bytes = self.size(unit="B")
					log.debug(f'VM file size is now: {total_bytes}')
					log.info("Successfully refreshed the size of the VM. Continuing with export...")
				# end VM file size checking/refreshing
				
				device_urls = []
				for device_url in lease.info.deviceUrl:
					if device_url.url.endswith(".nvram") and not include_nvram:
						continue
					elif not device_url.disk and not include_image_files:
						continue
					device_urls.append(device_url)
					if device_url.fileSize:
						total_bytes += device_url.fileSize

				# Download
				updater.start()
				ovf_files = list()
				for device_url in device_urls:
					url = device_url.url.replace("*", self._client.hostname)
					name = os.path.basename(device_url.url)
					temp_target = os.path.join(temp, name)
					with urllib.request.urlopen(url, context=ctx) as response, open(temp_target, 'wb') as out_file:
						if not response.status == 200:
							raise exceptions.VirtualMachineExportError(self.name, output_target, f"error while exporting file (status {response.status}): {response.read()}")
						while True:
							content = response.read(256 * 1024)
							if len(content) == 0:
								# Done
								break
							out_file.write(content)
							total_bytes_read += len(content)
							updater.progress = min(total_bytes_read / total_bytes * 100, 99)
						out_file.flush()
						os.fsync(out_file.fileno())
					ovf_file = pyVmomi.vim.OvfManager.OvfFile()
					ovf_file.deviceId = device_url.key
					ovf_file.path = name
					ovf_file.size = os.path.getsize(temp_target)
					ovf_files.append(ovf_file)

				# Done
				# Create OVF
				lease.HttpNfcLeaseProgress(99)
				ovf_manager = self._client._service_instance.content.ovfManager
				ovf_parameters = pyVmomi.vim.OvfManager.CreateDescriptorParams()
				ovf_parameters.name = self.name
				ovf_parameters.ovfFiles = ovf_files
				vm_descriptor_result = ovf_manager.CreateDescriptor(obj=self._vim_vm, cdp=ovf_parameters)
				if vm_descriptor_result.error:
					raise exceptions.VirtualMachineExportError(self.name, output_target, str(vm_descriptor_result.error[0].fault))
				vm_descriptor = vm_descriptor_result.ovfDescriptor
				target_ovf_descriptor_path = os.path.join(temp, self.name + '.ovf')
				with open(target_ovf_descriptor_path, 'wb') as f:
					f.write(str.encode(vm_descriptor))

				lease.HttpNfcLeaseProgress(100)
				lease.HttpNfcLeaseComplete()
			except Exception as e:
				lease.HttpNfcLeaseAbort()
				raise e
			finally:
				updater.done()
			
			# Move and convert the output
			ovf = OvfFile(temp)

			if not include_nvram:
				ovf.remove_config("nvram", extraconfig=True)

			ovf.create_manifest(hash_type=hash_type)
			if format == "ova":
				return ovf.as_ova(path, move=True)
			return ovf.as_ovf(path, move=True)

	def rename(self, new_name: str, folder_name: typing.Optional[str] = None, timeout: float = 30.0):
		"""
		Renames the VM as known by ESXi.
		Raises a 'RenameError' exception if the task fails or times out.

		:param new_name:
			The new name to give to the VM
		:param folder_name:
			The folder to contain the VM. The default is the folder the VM was originally in.
			Will create a new folder if one is not found with a matching name.
			Will throw an esxi_utils 'MultipleFoldersFoundError' exception if more than one folder is found with the given name.
		:param timeout:
			How long to wait for the rename task (in seconds) before throwing a RenameError exception.
		"""
		log.info(f"Renaming {self.name} to {new_name} ...")
		# call to API to rename VM
		rename_task = self._vim_vm.Rename(new_name)
		# wait for the task to complete
		start_time = time.time()
		while rename_task.info.state != 'success':
			s = rename_task.info.state
			if s == 'error':
				# e = rename_task.info.error if rename_task.info.error else None # this isn't always set (part of info)
				raise exceptions.RenameError(self._vm, f'Failed to rename VM! ... task info: {rename_task.info}')
			if s == 'queued':
				now = time.time()
				if now >= start_time + timeout:
					raise exceptions.RenameError(self._vm, f'Failed to rename VM! Timeout! ... task info: {rename_task.info}')
			# else state is either 'running' or 'success'
		log.info(f"Renamed! Name is now: {self.name}")

		# move the VM to a new folder if a name if provided
		if folder_name:
			log.info(f"Relocating {self.name} to folder with name: {folder_name} ...")
			root_folder = self.datastore._datacenter.vmFolder
			folder = VirtualMachineList._get_folder(root_folder, folder_name)
			if folder.name != root_folder.name:
				relocate_spec = pyVmomi.vim.vm.RelocateSpec()
				relocate_spec.folder = folder
				relocate_task = self._vim_vm.RelocateVM_Task(relocate_spec)
				# wait for the task to complete
				start_time = time.time()
				while relocate_task.info.state != 'success':
					s = relocate_task.info.state
					if s == 'error':
						raise exceptions.RenameError(self._vm, f'Failed to move VM to folder: "{folder_name}"! ... task info: {relocate_task.info}')
					if s == 'queued':
						now = time.time()
						if now >= start_time + timeout:
							raise exceptions.RenameError(self._vm, f'Failed to move VM to folder: "{folder_name}"! Timeout! ... task info: {relocate_task.info}')
					# else state is either 'running' or 'success'
				log.info(f"Relocated! VM is in folder: {folder_name}")
		# end if folder_name
	# end rename fn

	# ESXi can only seem to control the boot level at the hardware level
	# You still have to manually enter the BIOS and select the drive you want to boot from
	# def set_boot_disk(self, disk_label: str):
	# 	"""
	# 	Selects the disk called 'disk_label' from ESXi and sets it as the disk to boot from when the VM is powered on.

	# 	:param disk_label:
	# 		The 'label' (name) of the disk in ESXi to set as the first disk in the boot sequence
	# 	"""
	# 	log.info(f"Setting '{disk_label}' as the first disk to boot...")
	# 	boot_disk = None
	# 	for device in self._vim_vm.config.hardware.device:
	# 		if isinstance(device, pyVmomi.vim.vm.device.VirtualDisk) and device.deviceInfo.label == disk_label:
	# 			boot_disk = device
	# 			break
	# 	if not boot_disk:
	# 		raise exceptions.VirtualMachineHardwareError(self, f"Disk with label '{disk_label}' not found on the VM.")
		
	# 	boot_spec = pyVmomi.vim.vm.BootOptions.BootableDiskDevice(deviceKey=boot_disk.key)
	# 	boot_options = pyVmomi.vim.vm.BootOptions(bootOrder=[boot_spec])
	# 	config_spec = pyVmomi.vim.vm.ConfigSpec()
	# 	config_spec.bootOptions = boot_options
	# 	self._client._wait_for_task(
	# 		self._vim_vm.ReconfigVM_Task(spec=config_spec)
	# 	)
	# 	log.debug("Finished setting boot disk.")

	def force_bios_menu(self, enforce:bool = True):
		"""
		Forces the VM to enter the BIOS/boot menu the next time the VM boots.

		:param enforce:
			Whether to enforce this setting or not. Set this to False to disable this behavior.
		"""
		log.info(f"Setting enforce BIOS boot menu to '{enforce}'...")

		boot_options = pyVmomi.vim.vm.BootOptions(enterBIOSSetup=enforce)
		config_spec = pyVmomi.vim.vm.ConfigSpec()
		config_spec.bootOptions = boot_options
		self._client._wait_for_task(
			self._vim_vm.ReconfigVM_Task(spec=config_spec)
		)

	@property
	def _vim_vm(self):
		vm = pyVmomi.vim.VirtualMachine(self.id)
		vm._stub = self._client._service_instance._stub
		return vm

	def __str__(self):
		return f"<{type(self).__name__} '{self.name}' on {self._client.hostname}>"

	def __repr__(self):
		return str(self)
