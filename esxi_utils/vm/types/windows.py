from esxi_utils.vm.virtualmachine import VirtualMachine
from esxi_utils.util.connect.winrm import WinRMConnection
from esxi_utils.vm.tools.windows import WindowsGuestTools
import typing

if typing.TYPE_CHECKING:
	from esxi_utils.vm.types.ostype import OSType

class WindowsVirtualMachine(VirtualMachine):
	"""
	A Windows virtual machine on an ESXi host. 
	"""
	@property
	def winrm(self) -> typing.Type['WinRMConnection']:
		"""
		A WinRM connection object for establishing a remote connection to this Windows VM.
		"""
		return WinRMConnection

	@property
	def ostype(self) -> 'OSType':
		"""
		The `OSType` for this Virtual Machine.
		"""
		from esxi_utils.vm.types.ostype import OSType
		return OSType.Windows
	
	@property
	def tools(self) -> 'WindowsGuestTools':
		"""
		Get the VMware Tools object for this VM. Includes additional methods for interaction with a Windows operating system.
		"""
		return WindowsGuestTools(self)