from esxi_utils.util import log, exceptions
import pyVmomi
import typing

if typing.TYPE_CHECKING:
	from esxi_utils.client import ESXiClient
	from esxi_utils.vm.virtualmachine import VirtualMachine
	from esxi_utils.networking.distributedvswitch import DistributedVSwitch
	# from esxi_utils.networking.vmkernelnic import VMKernelNIC

class DistributedPortGroupList:
	"""
	The list of port groups on the ESXi host.
	"""
	def __init__(self, client: 'ESXiClient'):
		self._client = client

	def __iter__(self) -> typing.Iterator['DistributedPortGroup']:
		return iter([ DistributedPortGroup(self._client, pg.portgroupName) for pg in self._distributed_system ])

	def __getitem__(self, name) -> 'DistributedPortGroup':
		return self.get(name)

	def __contains__(self, name: str) -> bool:
		return self.exists(name)

	@property
	def items(self) -> typing.List['DistributedPortGroup']:
		"""
		A list of all items
		"""
		return list(self)

	def find(self, name: str) -> typing.Union['DistributedPortGroup', None]:
		"""
		Get a port group by name.

		:param name: The name of the port group.

		:return: A `PortGroup` object, or `None` if not found.
		"""
		found = [ pg for pg in self if pg.name == name ]
		if len(found) != 1:
			return None
		return found[0]

	def get(self, name: str) -> 'DistributedPortGroup':
		"""
		Get a port group by name and raise an exception if not found.

		:param name: The name of the port group.

		:return: A `PortGroup` object
		"""
		pg = self.find(name)
		if pg is None:
			raise exceptions.NetworkingObjectNotFoundError('PortGroup', name)
		return pg

	def exists(self, name: str) -> bool:
		"""
		Check whether a port group exists 

		:param name: The name of the port group

		:return: Whether or not the port group exists
		"""
		return self.find(name) is not None

	@property
	def _distributed_system(self):
		return self._client._host_system.parent.environmentBrowser.QueryConfigTarget().distributedVirtualPortgroup

	def __str__(self):
		return f"<{type(self).__name__} ({len(list(self))} Distributed Port Groups)>"
	
	def __repr__(self):
		return str(self)


class DistributedPortGroup:
	"""
	A Portgroup on the ESXi host.
	"""
	def __init__(self, client: 'ESXiClient', name: str):
		self._client = client
		self._name = name

	@property
	def name(self) -> str:
		"""
		The name of the port group.
		"""
		return self._name

	@property
	def vlan(self) -> int:
		"""
		The VLAN ID for ports using this port group. Possible values:
		- A value of 0 specifies that you do not want the port group associated with a VLAN.
		- A value from 1 to 4094 specifies a VLAN ID for the port group.
		- A value of 4095 specifies that the port group should use trunk mode, which allows the guest operating system to manage its own VLAN tags. 
		- A 'vim.NumericRange' object representing the range of available ports (contains a 'start' and an 'end' value to mark the range)
		"""
		return self._obj.portgroup.config.defaultPortConfig.vlan.vlanId

	# @property
	# def ports(self) -> typing.List[typing.Dict[str, str]]:
	# 	"""
	# 	The ports that currently exist and are used on this port group.
	# 	Returns a list of objects with the following keys:
	# 	- mac: The Media Access Control (MAC) address of network service of the virtual machine connected on this port. 
	# 	- type: The type of component connected on this port. One of:
	# 		- host: The VMkernel is connected to this port group. 
	# 		- systemManagement: A system management entity (service console) is connected to this port group. 
	# 		- unknown: This port group serves an entity of unspecified kind. 
	# 		- virtualMachine: A virtual machine is connected to this port group. 
	# 	"""
	# 	return [ { "mac": port.mac[0] if len(port.mac) else None, "type": port.type } for port in self._obj.port ]

	# @property
	# def active_clients(self) -> int:
	# 	"""
	# 	The number of active clients of this port group (the number of connections to powered-on virtual machines).
	# 	"""
	# 	return len([ port for port in self.ports if port["type"] == "virtualMachine" ])

	@property
	def vswitch(self) -> 'DistributedVSwitch':
		"""
		The Distributed VSwitch that this distributed port group belongs to.
		"""
		return self.distributed_vswitch

	@property
	def distributed_vswitch(self) -> 'DistributedVSwitch':
		"""
		The Distributed VSwitch that this distributed port group belongs to.
		"""
		from esxi_utils.networking.distributedvswitch import DistributedVSwitch
		return DistributedVSwitch(self._client, self._obj.switchName)

	# @property
	# def vmkernelnic(self) -> 'VMKernelNIC':
	# 	"""
	# 	The VMKernel NICs assigned to this port group, if any.
	# 	"""
	# 	host_ports = [ port for port in self.ports if port["type"] == "host" ]
	# 	if len(host_ports) == 0:
	# 		return None
	# 	if len(host_ports) > 1:
	# 		# Can there be multiple VMKernel NICs assigned to a port group?
	# 		# ESXi appears to only allow one, but this is uncertain so we log a warning here and future support
	# 		# for multiple may be added if a situation arises where this is not the case
	# 		log.warn(f"Mutiple host ports are assigned to {str(self)} but only one VMKernel NICs is supported.")
	# 	found = [ vnic for vnic in self._client.vmkernelnics if vnic.mac == host_ports[0]["mac"] ]
	# 	if len(found) == 0:
	# 		raise exceptions.NetworkingError(self, "No VMKernel NICs found")
	# 	return found[0]

	@property
	def vms(self) -> typing.List['VirtualMachine']:
		"""
		A list of the virtual machines attached to this distributed port group.
		"""
		vms = []
		for vm in self._client.vms:
			for nic in vm.nics:
				if nic.network == self.name:
					vms.append(vm)
					break
		return vms

	# def remove(self):
	# 	"""
	# 	Remove this port group from the system.
	# 	"""
	# 	self._network_system.RemovePortGroup(self.name)

	@property
	def _obj(self):
		for pg in self._distributed_system:
			if pg.portgroupName == self.name:
				return pg
		raise exceptions.NetworkingObjectNotFoundError('DistributedPortGroup', self.name)

	@property
	def _distributed_system(self):
		return self._client._host_system.parent.environmentBrowser.QueryConfigTarget().distributedVirtualPortgroup

	def __str__(self):
		return f"<{type(self).__name__} \"{self.name}\" vlan={self.vlan} on DistributedVSwitch \"{self.distributed_vswitch.name}\">"
	
	def __repr__(self):
		return str(self)