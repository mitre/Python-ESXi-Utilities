import typing
import enum

if typing.TYPE_CHECKING:
	from esxi_utils.vm.virtualmachine import VirtualMachine

class OSType(enum.Enum):
	#: OS Unknown
	Unknown = "unknown"

	#: Windows OS
	Windows = "windows"

	#: Linux OS
	Linux = "linux"

	#: Cisco-based OS
	Cisco = "cisco"

	#: Panorama-based OS
	PanOs = "panos"

	@staticmethod
	def map(ostype: typing.Optional['OSType']) -> 'VirtualMachine':
		"""
		Map an OSType value to the appropriate virtual machine class.

		:return: A VirtualMachine type
		"""
		from esxi_utils.vm.virtualmachine import VirtualMachine
		from esxi_utils.vm.types.cisco import CiscoVirtualMachine
		from esxi_utils.vm.types.linux import LinuxVirtualMachine
		from esxi_utils.vm.types.panos import PaloAltoFirewallVirtualMachine
		from esxi_utils.vm.types.windows import WindowsVirtualMachine

		typemap = {
			OSType.Windows: WindowsVirtualMachine,
			OSType.Linux: LinuxVirtualMachine,
			OSType.Cisco: CiscoVirtualMachine,
			OSType.PanOs: PaloAltoFirewallVirtualMachine
		}
		return typemap.get(ostype, VirtualMachine)

	@staticmethod
	def detect(guest_id: str) -> 'OSType':
		"""
		Attempt to detect the OSType from the given guest ID string.

		:param guest_id: The guest ID string.

		:return: The detected OSType.
		"""
		os = OSType.Unknown
		if guest_id and any([ keyword in guest_id.lower() for keyword in [ "ubuntu", "debian", "centos", "rhel", "linux" ] ]):
			os = OSType.Linux
		elif guest_id and any([ keyword in guest_id.lower() for keyword in [ "windows" ] ]):
			os = OSType.Windows
		return os