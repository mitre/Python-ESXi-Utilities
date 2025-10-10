from esxi_utils.vm.hardware.device import VirtualDevice, VirtualDeviceList
from esxi_utils.datastore import DatastoreFile
from esxi_utils.util import log, exceptions
import pyVmomi
import typing
import re

class VirtualFloppyList(VirtualDeviceList):
	"""
	The list of all virtual floppy drives on a Virtual Machine.
	"""
	def __iter__(self) -> typing.Iterator['VirtualFloppy']:
		floppies = [ dev for dev in super().__iter__() if isinstance(dev, VirtualFloppy) ]
		floppies.sort(key=lambda x: int(re.search(r"\d+", x.label).group(0)))
		return iter(floppies)

	def __getitem__(self, index) -> 'VirtualFloppy':
		return self.items[index]

	@property
	def items(self) -> 'VirtualFloppy':
		"""
		A list of all items
		"""
		return list(self)

	def add(self, filepath: 'DatastoreFile') -> 'VirtualFloppy':
		"""
		Add a new floppy drive to the VM's devices.

		:param filepath: A `DatastoreFile` object for a file in the datastore to add to the floppy

		:return: The `VirtualFloppy` object for the newly added floppy drive.
		"""
		log.info(f"{str(self)} Adding new floppy drive with file: {filepath}")
		assert isinstance(filepath, DatastoreFile), "filepath must be a DatastoreFile object"

		if len(list(self)) >= 2:
			raise exceptions.VirtualMachineInvalidHardwareConfigurationError(self._vm, "Maximum number of floppy drives (2) reached")

		controllers = VirtualDeviceList(self._vm).find_type("VirtualSIOController")
		if len(controllers) == 0:
			raise exceptions.VirtualMachineHardwareNotFoundError(self._vm, "SIO Controller", f"No controllers present to add floppy drive")
		controller = controllers[0]

		floppy_spec = pyVmomi.vim.vm.device.VirtualDeviceSpec()
		floppy_spec.operation = pyVmomi.vim.vm.device.VirtualDeviceSpec.Operation.add
		floppy_spec.device = pyVmomi.vim.vm.device.VirtualFloppy()
		floppy_spec.device.controllerKey = controller.key

		floppy_spec.device.backing = pyVmomi.vim.vm.device.VirtualFloppy.ImageBackingInfo()
		floppy_spec.device.backing.fileName = filepath.path

		floppy_spec.device.connectable = pyVmomi.vim.vm.device.VirtualDevice.ConnectInfo()
		floppy_spec.device.connectable.allowGuestControl = True
		floppy_spec.device.connectable.connected = False
		floppy_spec.device.connectable.startConnected = False
		return self._add_device(floppy_spec)


class VirtualFloppy(VirtualDevice):
	@property
	def file(self) -> 'DatastoreFile':
		"""
		The file attached to this floppy as a `DatastoreFile` object.
		"""
		return self._get_backing_file()

	@file.setter
	def file(self, filepath: 'DatastoreFile'):
		"""
		Set the file for this floppy. A floppy cannot be empty, and thus this can only change an attached file for another.

		:param filepath: A `DatastoreFile` object for a file in the datastore to add to the floppy.
		"""
		log.info(f"{str(self)} Updating file to: {filepath}")
		assert isinstance(filepath, DatastoreFile), "filepath must be a DatastoreFile object"

		floppy_spec = pyVmomi.vim.vm.device.VirtualDeviceSpec()
		floppy_spec.operation = pyVmomi.vim.vm.device.VirtualDeviceSpec.Operation.edit
		floppy_spec.device = self._obj
		floppy_spec.device.backing = pyVmomi.vim.vm.device.VirtualFloppy.ImageBackingInfo()
		floppy_spec.device.backing.fileName = filepath.path
		spec = pyVmomi.vim.vm.ConfigSpec()
		spec.deviceChange = [floppy_spec]
		self._vm._client._wait_for_task(
			self._vm._vim_vm.ReconfigVM_Task(spec=spec)
		)

	def __str__(self):
		return f"<{type(self).__name__}(file='{self.file}') for VM='{self._vm.name}'>"