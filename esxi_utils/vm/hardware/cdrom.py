from esxi_utils.vm.hardware.device import VirtualDevice, VirtualDeviceList
from esxi_utils.datastore import DatastoreFile
from esxi_utils.util import log, exceptions
import pyVmomi
import typing
import re

class VirtualCdromList(VirtualDeviceList):
	"""
	The list of all virtual CD-ROMs on a Virtual Machine.
	"""
	def __iter__(self) -> typing.Iterator['VirtualCdrom']:
		cdroms = [ dev for dev in super().__iter__() if isinstance(dev, VirtualCdrom) ]
		cdroms.sort(key=lambda x: int(re.search(r"\d+", x.label).group(0)))
		return iter(cdroms)

	def __getitem__(self, index) -> 'VirtualCdrom':
		return self.items[index]

	@property
	def items(self) -> 'VirtualCdrom':
		"""
		A list of all items
		"""
		return list(self)

	def add(self, filepath: typing.Optional['DatastoreFile'] = None) -> 'VirtualCdrom':
		"""
		Add a new CD-ROM to the VM's devices.

		:param path: A `DatastoreFile` object for a file in the datastore to add to the CD-ROM, or `None` to add no file.

		:return: The `VirtualCdrom` object for the newly added CD-ROM.
		"""
		log.info(f"{str(self)} Adding new CD-ROM with file: {filepath}")
		assert isinstance(filepath, DatastoreFile) or filepath is None, "filepath must be a DatastoreFile object or None"

		ides = VirtualDeviceList(self._vm).find_type("VirtualIDEController")
		if len(ides) == 0:
			raise exceptions.VirtualMachineHardwareNotFoundError(self._vm, "IDE Controller", f"No controllers present to add CD-ROM")

		target_ide = None
		for ide in ides:
			if ide._obj.device is None or len(ide._obj.device) < 2: # Maximum of 2 CD-ROMs per IDE
				target_ide = ide
				break
		else:
			raise exceptions.VirtualMachineHardwareNotFoundError(self._vm, "IDE Controller", f"No controllers present with sufficient capacity to add CD-ROM")

		cdrom_spec = pyVmomi.vim.vm.device.VirtualDeviceSpec()
		cdrom_spec.operation = pyVmomi.vim.vm.device.VirtualDeviceSpec.Operation.add
		cdrom_spec.device = pyVmomi.vim.vm.device.VirtualCdrom()
		cdrom_spec.device.controllerKey = target_ide.key

		cdrom_spec.device.connectable = pyVmomi.vim.vm.device.VirtualDevice.ConnectInfo()
		cdrom_spec.device.connectable.allowGuestControl = True
		
		if filepath:
			cdrom_spec.device.backing = pyVmomi.vim.vm.device.VirtualCdrom.IsoBackingInfo()
			cdrom_spec.device.backing.fileName = filepath.path
			cdrom_spec.device.connectable.connected  = False
			cdrom_spec.device.connectable.startConnected = False
		else:
			cdrom_spec.device.backing = pyVmomi.vim.vm.device.VirtualCdrom.AtapiBackingInfo()
			cdrom_spec.device.backing.useAutoDetect = True
		return self._add_device(cdrom_spec)


class VirtualCdrom(VirtualDevice):
	@property
	def file(self) -> typing.Union['DatastoreFile', None]:
		"""
		The file attached to this CD-ROM as a `DatastoreFile` object.
		"""
		return self._get_backing_file()

	@file.setter
	def file(self, filepath: typing.Optional["DatastoreFile"]):
		"""
		Set the file for this CD-ROM.

		:param filepath: A `DatastoreFile` object for a file in the datastore to add to the CD-ROM, or `None` to empty the CD-ROM.
		"""
		log.info(f"{str(self)} Updating file to: {filepath}")
		assert isinstance(filepath, DatastoreFile) or filepath is None, "filepath must be a DatastoreFile object or None"
		
		cdrom_spec = pyVmomi.vim.vm.device.VirtualDeviceSpec()
		cdrom_spec.operation = pyVmomi.vim.vm.device.VirtualDeviceSpec.Operation.edit
		cdrom_spec.device = self._obj

		if filepath:
			cdrom_spec.device.backing = pyVmomi.vim.vm.device.VirtualCdrom.IsoBackingInfo()
			cdrom_spec.device.backing.fileName = filepath.path
		else:
			cdrom_spec.device.backing = pyVmomi.vim.vm.device.VirtualCdrom.AtapiBackingInfo()
			cdrom_spec.device.backing.useAutoDetect = True

		spec = pyVmomi.vim.vm.ConfigSpec()
		spec.deviceChange = [cdrom_spec]
		self._vm._client._wait_for_task(
			self._vm._vim_vm.ReconfigVM_Task(spec=spec)
		)

	def __str__(self):
		return f"<{type(self).__name__}(file='{self.file}') for VM='{self._vm.name}'>"
