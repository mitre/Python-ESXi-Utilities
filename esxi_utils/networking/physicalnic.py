from esxi_utils.util import exceptions
import typing

if typing.TYPE_CHECKING:
	from esxi_utils.client import ESXiClient

class PhysicalNICList:
	"""
	The list of physical NICs on the ESXi host.
	"""
	def __init__(self, client: 'ESXiClient'):
		self._client = client

	def __iter__(self) -> typing.Iterator['PhysicalNIC']:
		return iter([ PhysicalNIC(self._client, pnic.device) for pnic in self._network_system.networkInfo.pnic ])

	def __getitem__(self, name) -> 'PhysicalNIC':
		return self.get(name)

	def __contains__(self, name: str) -> bool:
		return self.exists(name)

	@property
	def items(self) -> typing.List['PhysicalNIC']:
		"""
		A list of all items
		"""
		return list(self)

	def find(self, name: str) -> typing.Union['PhysicalNIC', None]:
		"""
		Get a Physical NIC by name.

		:param name: The name of the Physical NIC.

		:return: A `PhysicalNIC` object, or `None` if not found.
		"""
		found = [ pnic for pnic in self if pnic.name == name ]
		if len(found) != 1:
			return None
		return found[0]

	def get(self, name: str) -> 'PhysicalNIC':
		"""
		Get a Physical NIC by name and raise an exception if not found.

		:param name: The name of the Physical NIC.

		:return: A `PhysicalNIC` object
		"""
		pnic = self.find(name)
		if pnic is None:
			raise exceptions.NetworkingObjectNotFoundError('PhysicalNIC', name)
		return pnic

	def exists(self, name: str) -> bool:
		"""
		Check whether a Physical NIC exists 

		:parma name: The name of the Physical NIC

		:return: Whether or not the Physical NIC exists
		"""
		return self.find(name) is not None

	@property
	def _network_system(self):
		return self._client._host_system.configManager.networkSystem

	def __str__(self):
		return f"<{type(self).__name__} ({len(list(self))} Physical NICs)>"
	
	def __repr__(self):
		return str(self)


class PhysicalNIC:
	"""
	A physical network adapters as seen by the primary operating system. 
	"""
	def __init__(self, client: 'ESXiClient', name: str):
		self._client = client
		self._name = name

	@property
	def name(self) -> str:
		"""
		The device name of the physical network adapter.
		"""
		return self._name

	@property
	def up(self) -> bool:
		"""
		Whether or not this link is up.
		"""
		return (self._obj.linkSpeed is not None)

	@property
	def linkspeed(self) -> typing.Union[int, None]:
		"""
		Bit rate on the link, in megabits per second. If None, then the link is down. 
		"""
		if self._obj.linkSpeed:
			return self._obj.linkSpeed.speedMb
		return None

	@property
	def fullduplex(self) -> typing.Union[bool, None]:
		"""
		Flag to indicate whether or not the link is capable of full-duplex ("true") or only half-duplex ("false"). If None, then the link is down. 
		"""
		if self._obj.linkSpeed:
			return self._obj.linkSpeed.duplex
		return None
		
	@property
	def mac(self) -> str:
		"""
		The media access control (MAC) address of the physical network adapter. 
		"""
		return self._obj.mac

	@property
	def pci(self) -> str:
		"""
		Device hash of the PCI device corresponding to this physical network adapter. 
		"""
		return self._obj.pci

	@property
	def driver(self) -> str:
		"""
		The name of the driver.
		"""
		return self._obj.driver

	@property
	def _obj(self):
		for pnic in self._network_system.networkInfo.pnic:
			if pnic.device == self.name:
				return pnic
		raise exceptions.NetworkingObjectNotFoundError('PhysicalNIC', self.name)

	@property
	def _network_system(self):
		return self._client._host_system.configManager.networkSystem

	def __str__(self):
		return f"<{type(self).__name__} \"{self.name}\">"
	
	def __repr__(self):
		return str(self)