from esxi_utils.vm.virtualmachine import VirtualMachine
from esxi_utils.vm.tools.panos import PanosGuestTools
from esxi_utils.util.connect.panos import PanosAPIConnection, PanosSSHConnection
import typing

if typing.TYPE_CHECKING:
	from esxi_utils.vm.types.ostype import OSType

class PaloAltoFirewallVirtualMachine(VirtualMachine):
	"""
	A Palo Alto Firewall virtual machine on an ESXi host. 
	"""
	@property
	def api(self) -> typing.Type['PanosAPIConnection']:
		"""
		A connection object for establishing a remote connection to this Palo Alto Firewall's API.
		"""
		return PanosAPIConnection

	@property
	def ssh(self) -> typing.Type['PanosSSHConnection']:
		"""
		A SSH connection object for establishing a remote connection to this Palo Alto Firewall.
		"""
		return PanosSSHConnection

	@property
	def tools(self) -> 'PanosGuestTools':
		"""
		Get the VMware Tools object for this VM. Includes additional methods for interaction with the Palo Alto CLI.
		"""
		return PanosGuestTools(self)
	
	@property
	def ostype(self) -> 'OSType':
		"""
		The `OSType` for this Virtual Machine.
		"""
		from esxi_utils.vm.types.ostype import OSType
		return OSType.PanOs
	