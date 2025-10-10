from esxi_utils.vm.virtualmachine import VirtualMachine
from esxi_utils.util.connect.cisco import CiscoSSHConnection
import typing

if typing.TYPE_CHECKING:
	from esxi_utils.vm.types.ostype import OSType

class CiscoVirtualMachine(VirtualMachine):
	"""
	A Cisco virtual machine on an ESXi host. 
	"""
	@property
	def ssh(self) -> typing.Type['CiscoSSHConnection']:
		"""
		A SSH connection object for establishing a remote connection to this Cisco VM.
		"""
		return CiscoSSHConnection

	@property
	def ostype(self) -> 'OSType':
		"""
		The `OSType` for this Virtual Machine.
		"""
		from esxi_utils.vm.types.ostype import OSType
		return OSType.Cisco
		