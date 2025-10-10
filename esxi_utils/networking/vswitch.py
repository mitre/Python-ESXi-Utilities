from esxi_utils.util import log, exceptions
import pyVmomi
import typing

if typing.TYPE_CHECKING:
	from esxi_utils.client import ESXiClient
	from esxi_utils.networking.portgroup import PortGroup
	from esxi_utils.networking.physicalnic import PhysicalNIC

class VSwitchList:
	"""
	The list of virtual switches on the ESXi host.
	"""
	def __init__(self, client: 'ESXiClient'):
		self._client = client

	def __iter__(self) -> typing.Iterator['VSwitch']:
		return iter([ VSwitch(self._client, vswitch.name) for vswitch in self._network_system.networkInfo.vswitch ])

	def __getitem__(self, name) -> 'VSwitch':
		return self.get(name)

	def __contains__(self, name: str) -> bool:
		return self.exists(name)

	@property
	def items(self) -> typing.List['VSwitch']:
		"""
		A list of all items
		"""
		return list(self)

	def find(self, name: str) -> typing.Union['VSwitch', None]:
		"""
		Get a virtual switch by name.

		:param name: The name of the virtual switch.

		:return: A `VSwitch` object, or `None` if not found.
		"""
		found = [ vswitch for vswitch in self if vswitch.name == name ]
		if len(found) != 1:
			return None
		return found[0]

	def get(self, name: str) -> 'VSwitch':
		"""
		Get a virtual switch by name and raise an exception if not found.

		:param name: The name of the virtual switch.

		:return: A `VSwitch` object
		"""
		vswitch = self.find(name)
		if vswitch is None:
			raise exceptions.NetworkingObjectNotFoundError('VSwitch', name)
		return vswitch

	def exists(self, name: str) -> bool:
		"""
		Check whether a virtual switch exists 

		:param name: The name of the virtual switch

		:return: Whether or not the virtual switch exists
		"""
		return self.find(name) is not None

	def add(self, name: str, mtu: int = 1500, ports: int = 128) -> 'VSwitch':
		"""
		Adds a new virtual switch with the given name. The name must be unique with respect to other virtual switches on the host and is limited to 32 characters.

		:param name: The name for the new virtual switch.
		:param mtu: The maximum transmission unit (MTU) of the virtual switch in bytes. 
		:param ports: The number of ports that this virtual switch is configured to use. The maximum value is 1024, although other constraints, such as memory limits, may establish a lower effective limit.

		:return: The added `VSwitch` object.
		"""
		assert isinstance(name, str) and len(name) > 0, "name must be a string"
		assert len(name) < 32, "name must be limited to 32 characters"
		assert isinstance(mtu, int) and mtu > 0, "mtu must be a positive integer"
		assert isinstance(ports, int) and ports > 0, "ports must be a positive integer"
		assert ports <= 1024, "ports has a maximum value of 1024"

		log.info(f"Adding VSwitch \"{name}\" (mtu={mtu}, ports={ports})")
		self._network_system.AddVirtualSwitch(
			vswitchName=name, 
			spec=pyVmomi.vim.host.VirtualSwitch.Specification(
				mtu=mtu,
				numPorts=ports
			)
		)
		return VSwitch(self._client, name)

	@property
	def _network_system(self):
		return self._client._host_system.configManager.networkSystem

	def __str__(self):
		return f"<{type(self).__name__} ({len(list(self))} Virtual Switches)>"
	
	def __repr__(self):
		return str(self)


class VSwitch:
	"""
	A VSwitch on the ESXi host.
	"""
	def __init__(self, client: 'ESXiClient', name: str):
		self._client = client
		self._name = name

	@property
	def name(self) -> str:
		"""
		The name of the virtual switch.
		"""
		return self._name

	@property
	def portgroups(self) -> typing.List['PortGroup']:
		"""
		The Portgroups configured associated with this vswitch.
		"""
		from esxi_utils.networking.portgroup import PortGroup
		portgroups = self._obj.portgroup
		return [ PortGroup(self._client, pg.spec.name) for pg in self._network_system.networkInfo.portgroup if pg.key in portgroups ]

	@property
	def physicalnics(self) -> typing.List["PhysicalNIC"]:
		"""
		The set of physical network adapters associated with this virtual switch. 
		"""
		from esxi_utils.networking.physicalnic import PhysicalNIC
		pnics = self._obj.pnic
		return [ PhysicalNIC(self._client, pnic.device) for pnic in self._network_system.networkInfo.pnic if pnic.key in pnics ]

	@property
	def numports(self) -> int:
		"""
		The number of ports that this virtual switch currently has. 
		"""
		return self._obj.numPorts

	@property
	def numports_available(self) -> int:
		"""
		The number of ports that are available on this virtual switch. 
		There are a number of networking services that utilize a port on the virtual switch and are not accounted for in the Port array of a PortGroup. 
		For example, each physical NIC attached to a virtual switch consumes one port.
		"""
		return self._obj.numPortsAvailable

	@property
	def configured_ports(self) -> int:
		"""
		The number of ports that this virtual switch is configured to use. The maximum value is 1024, although other constraints, such as memory limits, may establish a lower effective limit. 
		"""
		return self._obj.spec.numPorts

	@property
	def mtu(self) -> int:
		"""
		The maximum transmission unit (MTU) associated with this virtual switch in bytes.
		"""
		return self._obj.mtu

	@property
	def beacon(self) -> typing.Union[int, None]:
		"""
		The beacon configuration to probe for the validity of a link.
		If this is `None`, beacon probing is disabled.
		If not `None`, this is the beacon interval (how often, in seconds, a beacon should be sent)
		"""
		if hasattr(self._obj.spec, "bridge") and self._obj.spec.bridge and hasattr(self._obj.spec.bridge, "beacon"):
			return self._obj.spec.bridge.beacon.interval
		return None

	@property
	def link_discovery_protocol(self) -> typing.Union[str, None]:
		"""
		The link discovery protocol configuration for the virtual switch.
		If this is `None`, this does not have a link discovery protocol.
		If not `None`, this is either `cdp` (Cisco Discovery Protocol) or `lldp` (Link Layer Discovery Protocol)
		"""
		if hasattr(self._obj.spec, "bridge") and self._obj.spec.bridge and hasattr(self._obj.spec.bridge, "linkDiscoveryProtocolConfig"):
			return self._obj.spec.bridge.linkDiscoveryProtocolConfig.protocol
		return None

	@property
	def link_discovery_operation(self) -> typing.Union[str, None]:
		"""
		The link discovery operation configuration for the virtual switch.
		If this is `None`, this does not have a link discovery protocol.
		If not `None`, this is one of the following:

		- `advertise`: 	Sent discovery packets for the switch, but don't listen for incoming discovery packets. 

		- `listen`: Listen for incoming discovery packets but don't sent discovery packet for the switch. 

		- `both`: Sent discovery packets for the switch and listen for incoming discovery packets. 

		- `none`: Don't listen for incoming discovery packets and don't sent discover packets for the switch either. 

		"""
		if hasattr(self._obj.spec, "bridge") and self._obj.spec.bridge and hasattr(self._obj.spec.bridge, "linkDiscoveryProtocolConfig"):
			return self._obj.spec.bridge.linkDiscoveryProtocolConfig.operation
		return None

	def add(self, name: str, vlan: int) -> 'PortGroup':
		"""
		Add a port group to this virtual switch.

		:param name: The name of the port group.
		:param vlan: The VLAN ID for ports using this port group. Possible values: 

		- A value of 0 specifies that you do not want the port group associated with a VLAN.

		- A value from 1 to 4094 specifies a VLAN ID for the port group.
		
		- A value of 4095 specifies that the port group should use trunk mode, which allows the guest operating system to manage its own VLAN tags.

		:return: The added `PortGroup` object.
		"""
		assert isinstance(name, str) and len(name) > 0, "name must be a string"
		assert isinstance(vlan, int) and vlan >= 0 and vlan <= 4095, "vlan must be a integer in range 0-4095"
		from esxi_utils.networking.portgroup import PortGroup
		self._network_system.AddPortGroup(
			portgrp=pyVmomi.vim.host.PortGroup.Specification(
				name=name,
				policy=pyVmomi.vim.host.NetworkPolicy(),
				vlanId=vlan,
				vswitchName=self.name
			)
		)
		return PortGroup(self._client, name)

	def remove(self):
		"""
		Remove this virtual switch from the system.
		"""
		self._network_system.RemoveVirtualSwitch(self.name)

	@property
	def _obj(self):
		for vswitch in self._network_system.networkInfo.vswitch:
			if vswitch.name == self.name:
				return vswitch
		raise exceptions.NetworkingObjectNotFoundError('VSwitch', self.name)

	@property
	def _network_system(self):
		return self._client._host_system.configManager.networkSystem

	def __str__(self):
		return f"<{type(self).__name__} \"{self.name}\" ({len(self.portgroups)} port groups)>"
	
	def __repr__(self):
		return str(self)