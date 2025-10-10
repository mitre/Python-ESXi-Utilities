from esxi_utils.util import exceptions
import typing

if typing.TYPE_CHECKING:
	from esxi_utils.client import ESXiClient
	from esxi_utils.networking.portgroup import PortGroup

class VMKernelNICList:
	"""
	The list of VMKernel NICs on the ESXi host.
	"""
	def __init__(self, client: 'ESXiClient'):
		self._client = client

	def __iter__(self) -> typing.Iterator['VMKernelNIC']:
		return iter([ VMKernelNIC(self._client, vnic.device) for vnic in self._network_system.networkInfo.vnic ])

	def __getitem__(self, name) -> 'VMKernelNIC':
		return self.get(name)

	def __contains__(self, name: str) -> bool:
		return self.exists(name)

	@property
	def items(self) -> typing.List['VMKernelNIC']:
		"""
		A list of all items
		"""
		return list(self)

	def find(self, name: str) -> typing.Union['VMKernelNIC', None]:
		"""
		Get a VMKernel NIC by name.

		:param name: The name of the VMKernel NIC.

		:return: A `VMKernelNIC` object, or `None` if not found.
		"""
		found = [ vnic for vnic in self if vnic.name == name ]
		if len(found) != 1:
			return None
		return found[0]

	def get(self, name: str) -> 'VMKernelNIC':
		"""
		Get a VMKernel NIC by name and raise an exception if not found.

		:param name: The name of the VMKernel NIC.

		:return: A `VMKernelNIC` object
		"""
		vnic = self.find(name)
		if vnic is None:
			raise exceptions.NetworkingObjectNotFoundError('VMKernelNIC', name)
		return vnic

	def exists(self, name: str) -> bool:
		"""
		Check whether a VMKernel NIC exists 

		:parma name: The name of the VMKernel NIC

		:return: Whether or not the VMKernel NIC exists
		"""
		return self.find(name) is not None

	@property
	def _network_system(self):
		return self._client._host_system.configManager.networkSystem

	def __str__(self):
		return f"<{type(self).__name__} ({len(list(self))} VMKernel NICs)>"
	
	def __repr__(self):
		return str(self)


class VMKernelNIC:
	"""
	A host virtual NIC that provides access to the external network through a virtual switch that is bridged through a VMKernel NIC to a physical network. 
	"""
	def __init__(self, client: 'ESXiClient', name: str):
		self._client = client
		self._name = name

	@property
	def name(self) -> str:
		"""
		The device name of this VMkernel NIC.
		"""
		return self._name

	@property
	def portgroup(self) -> typing.Union['PortGroup', None]:
		"""
		If the VMKernel NIC is connected to a vSwitch, this property is the `PortGroup` connected.
		"""
		from esxi_utils.networking.portgroup import PortGroup
		if self._obj.portgroup and len(self._obj.portgroup):
			return PortGroup(self._client, self._obj.portgroup)
		return None

	@property
	def mac(self) -> typing.Union[str, None]:
		"""
		Media access control (MAC) address of the virtual network adapter. 
		"""
		return self._obj.spec.mac

	@property
	def ip(self) -> typing.Union[str, None]:
		"""
		The IPv4 address currently used by the network adapter.
		"""
		if not self._obj.spec.ip:
			return None
		return self._obj.spec.ip.ipAddress

	@property
	def subnetmask(self) -> typing.Union[str, None]:
		"""
		The subnet mask, specified specified using IPv4 dot notation. 
		"""
		if not self._obj.spec.ip:
			return None
		return self._obj.spec.ip.subnetMask

	@property
	def gateway(self) -> typing.Union[str, None]:
		"""
		The default gateway address.
		"""
		if not self._obj.spec.ipRouteSpec or not self._obj.spec.ipRouteSpec.ipRouteConfig:
			return None
		return self._obj.spec.ipRouteSpec.ipRouteConfig.defaultGateway

	@property
	def mtu(self) -> int:
		"""
		Maximum transmission unit for packets size in bytes for the virtual NIC.
		"""
		return self._obj.spec.mtu

	@property
	def _obj(self):
		for vnic in self._network_system.networkInfo.vnic:
			if vnic.device == self.name:
				return vnic
		raise exceptions.NetworkingObjectNotFoundError('VMKernelNIC', self.name)

	@property
	def _network_system(self):
		return self._client._host_system.configManager.networkSystem

	def __str__(self):
		return f"<{type(self).__name__} \"{self.name}\">"
	
	def __repr__(self):
		return str(self)