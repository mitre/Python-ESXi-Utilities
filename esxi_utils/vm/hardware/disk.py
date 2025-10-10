from esxi_utils.vm.hardware.device import VirtualDevice, VirtualDeviceList
from esxi_utils.util import log, exceptions, parse
from esxi_utils.datastore import DatastoreFile
import pyVmomi
import typing
import re

class VirtualDiskList(VirtualDeviceList):
	"""
	The list of all virtual disks on a Virtual Machine.
	"""
	def __iter__(self) -> typing.Iterator['VirtualDisk']:
		disks = [ dev for dev in super().__iter__() if isinstance(dev, VirtualDisk) ]
		disks.sort(key=lambda x: int(re.search(r"\d+", x.label).group(0)))
		return iter(disks)

	def __getitem__(self, index) -> 'VirtualDisk':
		return self.items[index]

	@property
	def items(self) -> 'VirtualDisk':
		"""
		A list of all items
		"""
		return list(self)

	def add(self, size: typing.Union[str, int], scsi: int = 0, unit_number: typing.Optional[int] = None, thin: bool = True) -> 'VirtualDisk':
		"""
		Adds a disk to this VM.

		:param size:
			A string or integer representing the size of the new disk.
			If this is an integer, this represents a size in KB.
			If this is a string, the string is expected to take the form <number><unit>, where <unit> is one of KB, MB, or GB (e.g. 32GB).
		:param scsi:
			The number for the SCSI controller to attach the new disk to.
		:param unit_number:
			The unit number to assign the disk to on the provided controller. If `None`, the next available unit number will be used.
		:param thin:
			Whether or not this new disk should be thin provisioned.

		:return: The `VirtualDisk` object for the newly added disk.
		"""
		log.info(f"{str(self)} Adding new disk with size = {size}, scsi = {scsi}, unit number = {unit_number}, thin provisioning = {thin}")
		if isinstance(size, str):
			size = parse.size_string(size, unit="KB")
		if self._vm.snapshots.exists:
			raise exceptions.SnapshotsExistError(self._vm)
		
		# Find the requested SCSI controller
		scsi_controller = None
		for device in super().__iter__():
			if device.label == f"SCSI controller {scsi}":
				scsi_controller = device
				break
		else:
			raise exceptions.VirtualMachineHardwareNotFoundError(self._vm, "SCSI Controller", f"No SCSI {scsi} found")

		# Get the unit number if needed
		if unit_number is None:
			scsi_devices = scsi_controller._obj.device if scsi_controller._obj.device else []
			scsi_disks = [ disk for disk in self if disk.key in scsi_devices ]
			taken_unit_numbers = [ disk._obj.unitNumber for disk in scsi_disks ]
			available_unit_numbers = [ i for i in range(16) if i not in taken_unit_numbers ]
			if len(available_unit_numbers) == 0:
				raise exceptions.VirtualMachineHardwareError(self._vm, f"Failed to determine unit number for SCSI {scsi}")
			log.debug(f"{str(self)} Found next unit number for SCSI={scsi}: {available_unit_numbers[0]}")
			unit_number = available_unit_numbers[0]

		if not isinstance(unit_number, int) or unit_number < 0:
			raise ValueError(f"unit_number must be an integer greater or equal to 0")

		disk_spec = pyVmomi.vim.vm.device.VirtualDeviceSpec()
		disk_spec.fileOperation = "create"
		disk_spec.operation = pyVmomi.vim.vm.device.VirtualDeviceSpec.Operation.add
		disk_spec.device = pyVmomi.vim.vm.device.VirtualDisk()
		disk_spec.device.backing = pyVmomi.vim.vm.device.VirtualDisk.FlatVer2BackingInfo()
		if thin:
			disk_spec.device.backing.thinProvisioned = True
		disk_spec.device.backing.diskMode = 'persistent'
		disk_spec.device.unitNumber = unit_number
		disk_spec.device.capacityInKB = size
		disk_spec.device.controllerKey = scsi_controller.key
		return self._add_device(disk_spec)

	def add_existing_disk(self, filepath: typing.Optional['DatastoreFile'] = None, scsi: int = 0, unit_number: typing.Optional[int] = None) -> 'VirtualDisk':
		"""
		Adds an existing disk to this VM using a datastore file path.

		:param datastore_file_path:
			The full datastore file path to the existing virtual disk (e.g., '[datastore1] folder/disk.vmdk').
		:param scsi:
			The number for the SCSI controller to attach the disk to.
		:param unit_number:
			The unit number to assign the disk to on the provided controller. If `None`, the next available unit number will be used.

		:return: The `VirtualDisk` object for the newly added disk.
		"""
		assert isinstance(filepath, DatastoreFile) or filepath is None, "filepath must be a DatastoreFile object or None"
		log.info(f"{str(self)} Adding existing disk with datastore file path = {filepath}, scsi = {scsi}, unit number = {unit_number}")
		if self._vm.snapshots.exists:
			raise exceptions.SnapshotsExistError(self._vm)

		# Find the requested SCSI controller
		scsi_controller = None
		for device in super().__iter__():
			if device.label == f"SCSI controller {scsi}":
				scsi_controller = device
				break
		else:
			raise exceptions.VirtualMachineHardwareNotFoundError(self._vm, "SCSI Controller", f"No SCSI {scsi} found")

		# Get the unit number if needed
		if unit_number is None:
			scsi_devices = scsi_controller._obj.device if scsi_controller._obj.device else []
			scsi_disks = [disk for disk in self if disk.key in scsi_devices]
			taken_unit_numbers = [disk._obj.unitNumber for disk in scsi_disks]
			available_unit_numbers = [i for i in range(16) if i not in taken_unit_numbers]
			if len(available_unit_numbers) == 0:
				raise exceptions.VirtualMachineHardwareError(self._vm, f"Failed to determine unit number for SCSI {scsi}")
			log.debug(f"{str(self)} Found next unit number for SCSI={scsi}: {available_unit_numbers[0]}")
			unit_number = available_unit_numbers[0]

		if not isinstance(unit_number, int) or unit_number < 0:
			raise ValueError(f"unit_number must be an integer greater or equal to 0")

		# Create the disk specification for the existing disk
		disk_spec = pyVmomi.vim.vm.device.VirtualDeviceSpec()
		disk_spec.operation = pyVmomi.vim.vm.device.VirtualDeviceSpec.Operation.add
		disk_spec.device = pyVmomi.vim.vm.device.VirtualDisk()
		disk_spec.device.backing = pyVmomi.vim.vm.device.VirtualDisk.FlatVer2BackingInfo()
		disk_spec.device.backing.fileName = filepath.path
		disk_spec.device.backing.diskMode = 'persistent'
		disk_spec.device.unitNumber = unit_number
		disk_spec.device.controllerKey = scsi_controller.key

		return self._add_device(disk_spec)


class VirtualDisk(VirtualDevice):
	@property
	def size(self) -> int:
		"""
		The size of this disk in KB.
		"""
		return self._obj.capacityInKB

	@size.setter
	def size(self, size : typing.Union[str, int]):
		"""
		Modify the size of this disk.

		:param size:
			A string or integer representing the new size of this disk. The size must be greater or equal to the current disk size.
			If this is an integer, this represents a size in KB.
			If this is a string, the string is expected to take the form <number><unit>, where <unit> is one of KB, MB, or GB (e.g. 32GB).
		"""
		if isinstance(size, str):
			size = parse.size_string(size, unit="KB")
		log.info(f"{str(self)} Updating size to: {self.size}KB")

		if self._vm.snapshots.exists:
			raise exceptions.SnapshotsExistError(self._vm)
		if size <= self.size:
			raise exceptions.VirtualMachineInvalidHardwareConfigurationError(self._vm, f"specified disk size ({size}KB) must be greater than the existing disk size ({self.size}KB)")

		device_spec = pyVmomi.vim.vm.device.VirtualDeviceSpec()
		device_spec.operation = pyVmomi.vim.vm.device.VirtualDeviceSpec.Operation.edit
		device_spec.device = self._obj
		device_spec.device.capacityInKB = size
		spec = pyVmomi.vim.vm.ConfigSpec()
		spec.deviceChange = [device_spec]
		self._vm._client._wait_for_task(
			self._vm._vim_vm.ReconfigVM_Task(spec=spec)
		)

	@property
	def filepath(self) -> 'DatastoreFile':
		"""
		The path to this disk's file as a `DatastoreFile` object.
		"""
		return self._get_backing_file()

	def remove(self, delete_file: bool = True):
		"""
		Remove this disk from this virtual machine.

		:param delete_file: Delete the file from the datastore.
		"""
		log.info(f"{str(self)} Removing device")
		if self._vm.snapshots.exists:
			raise exceptions.SnapshotsExistError(self._vm)
		device_spec = pyVmomi.vim.vm.device.VirtualDeviceSpec()
		device_spec.operation = pyVmomi.vim.vm.device.VirtualDeviceSpec.Operation.remove
		if delete_file:
			device_spec.fileOperation = pyVmomi.vim.vm.device.VirtualDeviceSpec.FileOperation.destroy
		device_spec.device = self._obj
		spec = pyVmomi.vim.vm.ConfigSpec()
		spec.deviceChange = [device_spec]
		self._vm._client._wait_for_task(
			self._vm._vim_vm.ReconfigVM_Task(spec=spec)
		)

	def __str__(self):
		return f"<{type(self).__name__}(size={self.size}KB) for VM='{self._vm.name}'>"