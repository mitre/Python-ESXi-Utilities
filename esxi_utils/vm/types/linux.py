from esxi_utils.vm.virtualmachine import VirtualMachine
from esxi_utils.vm.tools.unix import UnixGuestTools
from esxi_utils.util.connect.unix import UnixSSHConnection
import typing

if typing.TYPE_CHECKING:
	from esxi_utils.vm.types.ostype import OSType

class LinuxVirtualMachine(VirtualMachine):
	"""
	A Linux virtual machine on an ESXi host. 
	"""
	@property
	def ssh(self) -> typing.Type['UnixSSHConnection']:
		"""
		An SSH connection object for establishing a remote connection to this Unix-like VM.
		"""
		return UnixSSHConnection

	@property
	def ostype(self) -> 'OSType':
		"""
		The `OSType` for this Virtual Machine.
		"""
		from esxi_utils.vm.types.ostype import OSType
		return OSType.Linux

	@property
	def tools(self) -> 'UnixGuestTools':
		"""
		Get the VMware Tools object for this VM. Includes additional methods for interaction with a Unix or Unix-like operating system.
		"""
		return UnixGuestTools(self)