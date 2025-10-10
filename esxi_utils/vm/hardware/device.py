from esxi_utils.util import log, exceptions
from esxi_utils.datastore import DatastoreFile
import pyVmomi
import typing

if typing.TYPE_CHECKING:
	from esxi_utils.vm.virtualmachine import VirtualMachine

class VirtualDeviceList:
	"""
	The list of all virtual devices on a Virtual Machine.
	"""
	def __init__(self, vm: 'VirtualMachine'):
		self._vm = vm
		self._vim_vm = self._vm._vim_vm

	def __iter__(self) -> typing.Iterator['VirtualDevice']:
		from esxi_utils.vm.hardware.nic import VirtualNIC
		from esxi_utils.vm.hardware.disk import VirtualDisk
		from esxi_utils.vm.hardware.cdrom import VirtualCdrom
		from esxi_utils.vm.hardware.floppy import VirtualFloppy
		from esxi_utils.vm.hardware.video_card import VirtualVideoCard

		devices = []
		for obj in self._vim_vm.config.hardware.device:
			device = None
			key = obj.key
			if isinstance(obj, pyVmomi.vim.vm.device.VirtualEthernetCard):
				device = VirtualNIC(self._vm, key)
			elif isinstance(obj, pyVmomi.vim.vm.device.VirtualDisk):
				device = VirtualDisk(self._vm, key)
			elif isinstance(obj, pyVmomi.vim.vm.device.VirtualCdrom):
				device = VirtualCdrom(self._vm, key)
			elif isinstance(obj, pyVmomi.vim.vm.device.VirtualFloppy):
				device = VirtualFloppy(self._vm, key)
			elif isinstance(obj, pyVmomi.vim.vm.device.VirtualVideoCard):
				device = VirtualVideoCard(self._vm, key)
			else:
				device = VirtualDevice(self._vm, key)
			devices.append(device)
		return iter(devices)

	def __getitem__(self, index) -> 'VirtualDevice':
		return self.items[index]

	@property
	def items(self) -> 'VirtualDevice':
		"""
		A list of all items
		"""
		return list(self)

	def _add_device(self, device_spec) -> 'VirtualDevice':
		"""
		Add a new device using the provided VirtualDeviceSpec. 
		This function provides additional functionality to attempt to retrieve the added device after adding.
		Note: This function is not thread-safe as it may retrieve another device of the same type if another was simultaneously added elsewhere.

		:param device_spec: A `VirtualDeviceSpec` for the device to add.

		:return: A `VirtualDevice` (or subclass) for the added device. 
		"""
		dtype = type(device_spec.device)
		current_device_keys = [ obj.key for obj in self._vim_vm.config.hardware.device if isinstance(obj, dtype) ]
		spec = pyVmomi.vim.vm.ConfigSpec()
		spec.deviceChange = [device_spec]
		self._vm._client._wait_for_task(self._vim_vm.ReconfigVM_Task(spec=spec))
		added_device_keys = [ obj.key for obj in self._vim_vm.config.hardware.device if isinstance(obj, dtype) and obj.key not in current_device_keys ]
		added_devices = [ device for device in self if device.key in added_device_keys ]
		if len(added_devices) == 0:
			raise exceptions.VirtualMachineHardwareNotFoundError(self._vm, str(dtype), f"Failed to find newly added device")
		if len(added_devices) > 1:
			raise exceptions.VirtualMachineHardwareNotFoundError(self._vm, str(dtype), f"multiple added devices found (another device may have been added simultaneously in another thread)")
		return added_devices[0]

	def find_type(self, dtype: str) -> typing.List['VirtualDevice']:
		"""
		Find devices by their type. The type can be provided as its real value (e.g. "VirtualDisk") or as its shorthand (e.g. "disk")

		:param dtype: The type of device to get (e.g. IDEController).

		:return: List of `VirtualDevice` objects for each device matching the provided type.
		"""
		found = []
		for device in self:
			device_dtype = device._dtype.lower()
			device_dtype_shorthand = device_dtype.replace("virtual", "", 1)
			if dtype.lower() == device_dtype or dtype.lower() == device_dtype_shorthand:
				found.append(device)
		return found

	def __str__(self):
		return f"<{type(self).__name__} for {self._vm.name} ({len(list(self))} devices)>"

	def __repr__(self):
		return str(self)
		

class VirtualDevice:
	"""
	Represents a generic device on a VirtualMachine.
	"""
	def __init__(self, vm: 'VirtualMachine', key: int):
		self._vm = vm
		self._key = key

	@property
	def key(self) -> int:
		"""
		A unique key that distinguishes this device from other devices in the same virtual machine. 
		Keys are immutable but may be recycled; that is, a key does not change as long as the device is associated with a particular virtual machine. 
		However, once a device is removed, its key may be used when another device is added. 
		"""
		return self._key

	@property
	def label(self) -> str:
		"""
		The device's label
		"""
		if self._obj.deviceInfo and hasattr(self._obj.deviceInfo, "label"):
			return self._obj.deviceInfo.label.strip()
		return ""

	@property
	def connectable(self) -> bool:
		"""
		Whether or not this device is connectable. Certain functions will fail if a device is not connectable.
		"""
		return self._obj.connectable is not None

	def _assert_connectable(self):
		if not self.connectable:
			raise exceptions.VirtualMachineHardwareNotConnectableError(self._vm, self)

	@property
	def start_connected(self) -> bool:
		"""
		Whether or not this device is set to start connected.
		"""
		self._assert_connectable()
		return self._obj.connectable.startConnected

	@start_connected.setter
	def start_connected(self, value: bool):
		"""
		Set whether or not this device should start connected.
		"""
		self._assert_connectable()
		log.info(f"{str(self)} Setting device start-connected to \"{value}\"")
		device_spec = pyVmomi.vim.vm.device.VirtualDeviceSpec()
		device_spec.operation = pyVmomi.vim.vm.device.VirtualDeviceSpec.Operation.edit
		device_spec.device = self._obj
		device_spec.device.connectable.startConnected = value
		spec = pyVmomi.vim.vm.ConfigSpec()
		spec.deviceChange = [device_spec]
		self._vm._client._wait_for_task(
			self._vm._vim_vm.ReconfigVM_Task(spec=spec)
		)

	@property
	def connected(self) -> bool:
		"""
		Whether or not this device is connected.
		"""
		self._assert_connectable()
		return self._obj.connectable.connected

	@connected.setter
	def connected(self, value: bool):
		"""
		Connect or disconnect this device.
		"""
		self._assert_connectable()
		log.info(f"{str(self)} Setting device connected to \"{value}\"")
		device_spec = pyVmomi.vim.vm.device.VirtualDeviceSpec()
		device_spec.operation = pyVmomi.vim.vm.device.VirtualDeviceSpec.Operation.edit
		device_spec.device = self._obj
		device_spec.device.connectable.connected = value
		spec = pyVmomi.vim.vm.ConfigSpec()
		spec.deviceChange = [device_spec]
		self._vm._client._wait_for_task(
			self._vm._vim_vm.ReconfigVM_Task(spec=spec)
		)

	def remove(self):
		"""
		Remove this device.
		"""
		log.info(f"{str(self)} Removing device")
		device_spec = pyVmomi.vim.vm.device.VirtualDeviceSpec()
		device_spec.operation = pyVmomi.vim.vm.device.VirtualDeviceSpec.Operation.remove
		device_spec.device = self._obj
		spec = pyVmomi.vim.vm.ConfigSpec()
		spec.deviceChange = [device_spec]
		self._vm._client._wait_for_task(
			self._vm._vim_vm.ReconfigVM_Task(spec=spec)
		)

	def _get_backing_file(self) -> typing.Union['DatastoreFile', None]:
		"""
		Get the full path to the backing file.

		:return: A `DatastoreFile` object, or `None` if it does not exist.
		"""
		if self._obj.backing is None or not hasattr(self._obj.backing, "fileName"):
			return None
		return DatastoreFile.parse(self._vm._client, self._obj.backing.fileName)
	
	@property
	def _obj(self):
		for dev in self._vm._vim_vm.config.hardware.device:
			if dev.key == self.key:
				return dev
		raise exceptions.VirtualMachineHardwareNotFoundError(self._vm, type(self).__name__, f"No device with key {self.key}")

	@property
	def _dtype(self):
		return self._obj._wsdlName

	def __str__(self):
		return f"<{type(self).__name__}(dtype={self._dtype}, label=\"{self.label}\") for VM=\"{self._vm.name}\">"

	def __repr__(self):
		return str(self)