from esxi_utils.vm.hardware.device import VirtualDevice, VirtualDeviceList
from esxi_utils.util import log, exceptions
import pyVmomi
import typing
import time
import re

class VirtualNICList(VirtualDeviceList):
	"""
	The list of all virtual NICs on a Virtual Machine.
	"""
	def __iter__(self) -> typing.Iterator['VirtualNIC']:
		nics = [ dev for dev in super().__iter__() if isinstance(dev, VirtualNIC) ]
		nics.sort(key=lambda x: int(re.search(r"\d+", x.label).group(0)))
		return iter(nics)

	def __getitem__(self, name_or_index) -> 'VirtualNIC':
		if isinstance(name_or_index, str):
			return self.get(name_or_index)
		else:
			return super().__getitem__(name_or_index)

	def __contains__(self, name: str):
		return self.exists(name)

	def find(self, network: str) -> typing.Union['VirtualNIC', None]:
		"""
		Get the NIC assigned to this VM associated with the given network.

		:param network: The name of the network (portgroup) for the NIC to get.

		:return: A `VirtualNIC` object, or `None` if not found.
		"""
		found = [ nic for nic in self if nic.network == network ]
		if len(found) == 0:
			return None
		if len(found) > 1:
			raise exceptions.VirtualMachineHardwareNotFoundError(self._vm, "VirtualNIC", f"Multiple NICs connected to network {network}")
		return found[0]

	def get(self, network: str) -> 'VirtualNIC':
		"""
		Get the NIC assigned to this VM associated with the given network and raise an exception if not found.

		:param network: The name of the network (portgroup) for the NIC to get.

		:return: A `VirtualNIC` object.
		"""
		nic = self.find(network)
		if nic is None:
			raise exceptions.VirtualMachineHardwareNotFoundError(self._vm, "VirtualNIC", f"Unable to find NIC for network {network}")
		return nic

	def exists(self, network: str) -> bool:
		"""
		Check whether a NIC exists on this virtual machine for the provided network.

		:parma network: The name of the network (portgroup).

		:return: Whether or not a NIC exists connected to this network.
		"""
		return any([nic.network == network for nic in self])

	def add(self, network: str, adapter_type: str = "vmxnet3", pci_slot: typing.Optional[int] = None) -> 'VirtualNIC':
		"""
		Adds a network to the VM.

		:param network: The name of the network (portgroup) to assign to the new nic.
		:param adapter_type: The adapter type to use for the interface
		:param pci_slot: The PCI slot to use for the network interface. For some systems, the interface name is based on the PCI slot 

		:return: The `VirtualNIC` object for the newly added NIC.
		"""
		log.info(f"{str(self)} Adding new virtual NIC with network = {network}, adapter type = {adapter_type}, pci_slot = {pci_slot}")
		assert isinstance(network, str), "network must be a string"
		assert isinstance(adapter_type, str), "adapter_type must be a string"
		assert (isinstance(pci_slot, int) and pci_slot >= 0) or pci_slot is None, "pci_slot must be an integer greater than 0, or None"
		
		# Check that the network exists
		pg = self._vm._client._get_network_object_from_host_system(network)

		ethernet_device_map = {
			"vmxnet": pyVmomi.vim.vm.device.VirtualVmxnet,
			"vmxnet2": pyVmomi.vim.vm.device.VirtualVmxnet2,
			"vmxnet3": pyVmomi.vim.vm.device.VirtualVmxnet3,
			"e1000": pyVmomi.vim.vm.device.VirtualE1000,
			"e1000e": pyVmomi.vim.vm.device.VirtualE1000e,
			"pcnet32": pyVmomi.vim.vm.device.VirtualPCNet32,
			"sriov": pyVmomi.vim.vm.device.VirtualSriovEthernetCard,
		}

		# Get device type
		if adapter_type.lower() not in ethernet_device_map:
			raise exceptions.VirtualMachineInvalidHardwareConfigurationError(self._vm, f"Ethernet device type \"{adapter_type}\" does not exist")
		device = ethernet_device_map[adapter_type]()
		device.wakeOnLanEnabled = True
		device.addressType = 'generated'
		if pci_slot is not None:
			# Check that the PCI slot is not used
			# We need to check this explicitly since an error won't be thrown
			# by default if it is already used
			duplicates = [ n for n in self if str(n.pci) == str(pci_slot) ]
			if len(duplicates) > 0:
				raise exceptions.VirtualMachineInvalidHardwareConfigurationError(self._vm, f"PCI slot {pci_slot} is already in use by NIC {duplicates[0].network}")
			device.slotInfo = pyVmomi.vim.vm.device.VirtualDevice.PciBusSlotInfo(pciSlotNumber=pci_slot)

		# Create device spec
		nic_spec = pyVmomi.vim.vm.device.VirtualDeviceSpec()
		nic_spec.operation = pyVmomi.vim.vm.device.VirtualDeviceSpec.Operation.add
		nic_spec.device = device

		if isinstance(pg, pyVmomi.vim.dvs.DistributedVirtualPortgroup):
			nic_spec.device.backing = pyVmomi.vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo()
			nic_spec.device.backing.port = pyVmomi.vim.DistributedVirtualSwitchPortConnection()
			dpg = self._find_distributed_portgroup(pg._moId)
			if dpg is None:
				raise exceptions.ESXiAPIObjectNotFoundError(pyVmomi.vim.Network, f"distributed network: {network} ... not found")
			nic_spec.device.backing.port.switchUuid = dpg.switchUuid
			nic_spec.device.backing.port.portgroupKey = dpg.portgroupKey
		else: # not distributed
			nic_spec.device.backing = pyVmomi.vim.vm.device.VirtualEthernetCard.NetworkBackingInfo()
			nic_spec.device.backing.useAutoDetect = False
			nic_spec.device.backing.deviceName = network

		nic_spec.device.connectable = pyVmomi.vim.vm.device.VirtualDevice.ConnectInfo()
		nic_spec.device.connectable.startConnected = True
		nic_spec.device.connectable.allowGuestControl = True
		nic_spec.device.connectable.connected = True
		nic_spec.device.connectable.status = 'untried'

		return self._add_device(nic_spec)

	def _find_distributed_portgroup(self, moId_or_portgroupKey: str) -> pyVmomi.vim.dvs.DistributedVirtualPortgroupInfo:
		"""
		Finds the distributed portgroup with the given _moId or portgroupKey by querying the Environment Browser
		for the portgroupKey that matches the NIC's port backing.
		"""
		all_distributed_portgroups = self._vm._client._host_system.parent.environmentBrowser.QueryConfigTarget().distributedVirtualPortgroup
		for dpg in all_distributed_portgroups:
			if dpg.portgroupKey == moId_or_portgroupKey:
				return dpg
		return None

class VirtualNIC(VirtualDevice):
	@property
	def network(self) -> str:
		"""
		The name of the network associated with this NIC.
		"""
		if self.distributed:
			dpg = self._get_distributed_portgroup
			return dpg.portgroupName if dpg is not None else ""
		return self._obj.backing.deviceName

	@network.setter
	def network(self, value: str):
		"""
		Set the network associated with this NIC.
		"""
		log.info(f"{str(self)} Updating network to: \"{value}\"")
		if self.distributed:
			raise exceptions.VirtualMachineInvalidHardwareConfigurationError(self._vm, "Network assignment to a distributed virtual ethernet card is not supported")
		
		self._vm._client._get_network_object_from_host_system(value) # Check that the network to add exists	
		nic_spec = pyVmomi.vim.vm.device.VirtualDeviceSpec()
		nic_spec.operation = pyVmomi.vim.vm.device.VirtualDeviceSpec.Operation.edit
		nic_spec.device = self._obj
		nic_spec.device.backing.deviceName = value
		
		spec = pyVmomi.vim.vm.ConfigSpec()
		spec.deviceChange = [nic_spec]
		self._vm._client._wait_for_task(
			self._vm._vim_vm.ReconfigVM_Task(spec=spec)
		)

	@property
	def _get_distributed_portgroup(self) -> pyVmomi.vim.dvs.DistributedVirtualPortgroupInfo:
		"""
		Finds the distributed portgroup associated with this nic by querying the Environment Browser
		for the portgroupKey that matches the NIC's port backing.
		"""
		all_distributed_portgroups = self._vm._client._host_system.parent.environmentBrowser.QueryConfigTarget().distributedVirtualPortgroup
		for dpg in all_distributed_portgroups:
			if dpg.portgroupKey == self._obj.backing.port.portgroupKey:
				return dpg
		return None

	@property
	def pci(self) -> int:
		"""
		The PCI slot number associated with this NIC.
		"""
		try:
			return self._obj.slotInfo.pciSlotNumber
		except AttributeError as e:
			if 'pciSlotNumber' in str(e):
				log.critical(f'Unable to determine PCI slot number for network interface: {self} ... Remove the interface and add it again.')
			raise e

	@property
	def mac(self) -> str:
		"""
		The MAC address associated with this NIC.
		"""
		return self._obj.macAddress

	@property
	def distributed(self) -> bool:
		"""
		Whether this virtual ethernet card connects to a distributed virtual switch port or portgroup.
		"""
		return isinstance(self._obj.backing, pyVmomi.vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo)

	@property
	def ip(self) -> typing.Union[str, None]:
		"""
		Attempt to detect the VM's IPv4 address on this NIC.
		"""
		# Try to detect with VMware tools first as this is more accurate (and faster)
		if self._vm.tools.running:
			for network in self._vm.tools.networks:
				if network["mac"] == self.mac:
					return network["ips"][0]

		# Fall back to detecting with esxcli
		with self._vm._client.ssh() as conn:
			for port in conn.esxcli(f"network vm port list -w {self._vm.get_world_id()}"):
				if port['MACAddress'] == self.mac:
					ip = port['IPAddress']
					if re.match(r"^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$", ip) is None or ip == "0.0.0.0":
						continue
					return ip
		return None

	def wait(self, retries: int = 60, delay: int = 2) -> typing.Union[str, None]:
		"""
		Waits for a NIC to become available with an IPv4 address.

		:param retries: How many times to retry detecting an IP on the given network before exiting.
		:param delay: How long to pause between retries in seconds.

		:return: The VM's IPv4 address on the network, or `None` if not found.
		"""
		for _ in range(retries):
			ip = self.ip
			if ip:
				return ip
			time.sleep(delay)
		return None

	def __str__(self):
		return f"<{type(self).__name__}(network='{self.network}') for VM='{self._vm.name}'{' (distributed)' if self.distributed else ''}>"
