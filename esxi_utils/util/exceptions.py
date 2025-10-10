class ESXiUtilsException(Exception):
	"""Base class for all esxi_util library exceptions."""
	pass


class VirtualMachineNotFoundError(ESXiUtilsException):
	"""
	Raised when a virtual machine is not found.
	
	:param name_or_id: The name (string) or id (int) of the virtual machine
	"""
	def __init__(self, name_or_id):
		super().__init__(f"Virtual machine with {'ID' if isinstance(name_or_id, int) else 'name'} \"{name_or_id}\" not found")


class MultipleVirtualMachinesFoundError(ESXiUtilsException):
	"""
	Raised when multiple virtual machines are found but only one was expected.
	
	:param name_or_id: The name (string) or id (int) of the virtual machine
	"""
	def __init__(self, name_or_id):
		super().__init__(f"Multiple virtual machines with {'ID' if isinstance(name_or_id, int) else 'name'} \"{name_or_id}\" found")


class VirtualMachineExistsError(ESXiUtilsException):
	"""
	Raised when a virtual machine already exists.
	
	:param name: The name of the virtual machine/
	"""
	def __init__(self, name):
		super().__init__(f"A virtual machine with name \"{name}\" already exists")


class SnapshotNotFoundError(ESXiUtilsException):
	"""
	Raised when a virtual machine snapshot is not found
	
	:param vm: The VirtualMachine object
	:param name_or_id: The name (string) or id (int) of the snapshot
	"""
	def __init__(self, vm, name_or_id):
		super().__init__(f"Unable to find snapshot with {'ID' if isinstance(name_or_id, int) else 'name'} \"{name_or_id}\" for virtual machine {str(vm)}")


class MultipleSnapshotsFoundError(ESXiUtilsException):
	"""
	Raised when multiple virtual machine snapshots are found but only one was expected
	
	:param vm: The VirtualMachine object
	:param name_or_id: The name (string) or id (int) of the snapshot
	"""
	def __init__(self, vm, name_or_id):
		super().__init__(f"Multiple snapshots with {'ID' if isinstance(name_or_id, int) else 'name'} \"{name_or_id}\" found for virtual machine {str(vm)}")


class SnapshotsExistError(ESXiUtilsException):
	"""
	Raised when a virtual machine has snapshots but was expected not to have any.

	:param vm: The VirtualMachine object.
	"""
	def __init__(self, vm):
		super().__init__(f"Virtual machine {str(vm)} has snapshots")


class DatastoreError(ESXiUtilsException):
	"""
	Raised when an error is experienced related to a datastore.

	:param datastore: The datastore.
	:param reason: The reason for the error.
	"""
	def __init__(self, datastore, reason):
		super().__init__(f"Error for datastore {str(datastore)}: {str(reason)}")


class DatastoreNotFoundError(DatastoreError):
	"""
	Raised when an a datastore is not found.

	:param datastore: The datastore name.
	"""
	def __init__(self, datastore):
		super().__init__(datastore, "Not found")


class DatastoreSpaceError(DatastoreError):
	"""
	Raised when a datastore has insufficient space to complete an operation.
	
	:param datastore: The datastore.
	:param required: The space required.
	:param available: The space available.
	"""
	def __init__(self, datastore, required, available):
		super().__init__(datastore, f"Insufficient free space to complete this operation (required: {required}, available: {available})")


class DatastoreFileNotFoundError(DatastoreError):
	"""
	Raised when an a datastore file or directory is not found.

	:param datastore: The datastore.
	:param path: The path to the file
	"""
	def __init__(self, datastore, path):
		super().__init__(datastore, f"File or directory {path} not found")


class DatastoreFileExistsError(DatastoreError):
	"""
	Raised when a datastore file or directory exists but was expected not to exist.

	:param datastore: The datastore.
	:param path: The path to the file or directory.
	"""
	def __init__(self, datastore, path):
		super().__init__(datastore, f"File or directory {path} already exists")


class DatastoreNotADirectoryError(DatastoreError):
	"""
	Raised when a datastore path is not a directory when it was expected to be.

	:param datastore: The datastore.
	:param path: The path to the directory.
	"""
	def __init__(self, datastore, path):
		super().__init__(datastore, f"Path {path} is not a directory")


class DatastoreIsADirectoryError(DatastoreError):
	"""
	Raised when a path is a directory when it was expected not to be.

	:param datastore: The datastore.
	:param path: The path to the directory.
	"""
	def __init__(self, datastore, path):
		super().__init__(datastore, f"Path {path} is a directory")


class OvfImportError(ESXiUtilsException):
	"""
	Raised when an OVF or OVA has failed to import.
	
	:param path: The path to the OVF/OVA file.
	:param datastore: The name of the datastore that the OVF/OVA is being imported into.
	:param name: The name of the virtual machine that the OVF/OVA is being imported as.
	:param reason: The reason for the failure.
	"""
	def __init__(self, path, datastore, name, reason):
		super().__init__(f"Failed to import {path} as virtual machine \"{name}\" in datastore \"{datastore}\": {reason}")


class VirtualMachineExportError(ESXiUtilsException):
	"""
	Raised when a virtual machine has failed to export as OVF/OVA.
	
	:param name: The name of the virtual machine.
	:param path: The path to the file that the virtual machine is being exported to.
	:param reason: The reason for the failure.
	"""
	def __init__(self, name, path, reason):
		super().__init__(f"Failed to export virtual machine \"{name}\" to {path}: {reason}")


class VirtualMachinePowerError(ESXiUtilsException):
	"""Raised when a virtual machine is not in the desired power state."""


class VirtualMachineNotPoweredOffError(VirtualMachinePowerError):
	"""
	Raised when a virtual machine is not powered off but was expected to be.
	
	:param name: The name of the virtual machine.
	"""
	def __init__(self, name):
		super().__init__(f"Virtual machine \"{name}\" is not powered off")


class VirtualMachineAlreadyPoweredOffError(VirtualMachinePowerError):
	"""
	Raised when a virtual machine is already powered off.
	
	:param name: The name of the virtual machine.
	"""
	def __init__(self, name):
		super().__init__(f"Virtual machine \"{name}\" is already powered off")


class VirtualMachineNotPoweredOnError(VirtualMachinePowerError):
	"""
	Raised when a virtual machine is not powered on but was expected to be.
	
	:param name: The name of the virtual machine.
	"""
	def __init__(self, name):
		super().__init__(f"Virtual machine \"{name}\" is not powered on")
	

class VirtualMachineAlreadyPoweredOnError(VirtualMachinePowerError):
	"""
	Raised when a virtual machine is already powered on.
	
	:param name: The name of the virtual machine.
	"""
	def __init__(self, name):
		super().__init__(f"Virtual machine \"{name}\" is already powered on")


class ESXiShellCommandError(ESXiUtilsException):
	"""
	Raised when an ESXi shell command, or a functionality dependent on an ESXi shell command, fails.
	
	:param cmd: The command run.
	:param reason: Reason for the failure.
	:param output: Raw output of the command.
	"""
	def __init__(self, cmd, reason, output):
		super().__init__(f"ESXi shell command failure (command: \"{cmd}\"; reason: {reason}). Output: {str(output)}")


class OvfFileError(ESXiUtilsException):
	"""
	Raised when there is a failure in an OVF/OVA file itself.

	:param path: The path to the OVF file.
	:param reason: The reason for the failure.
	"""
	def __init__(self, path, reason):
		super().__init__(f"Error for file {path}: {reason}")


class OvfManifestError(OvfFileError):
	"""Raised when the manifest fails to validate for an OVF/OVA file."""


class OvfFileNotFoundError(OvfFileError):
	"""Raised when a specified OVF/OVA file is not found or is not a valid OVF/OVA file."""


class OvfAmbiguityError(OvfFileError):
	"""Raised when there is ambiguity related to an OVF/OVA file, such as when multiple matching OVF files exist."""


class RemoteConnectionError(ESXiUtilsException):
	"""
	Raised when there is an issue related to a remote connection.

	:param connection_str: A connection string used to identify the connection being made.
	:param reason: The reason for the error.
	"""
	def __init__(self, connection_str, reason):
		super().__init__(f"Connection error for {str(connection_str)}: {str(reason)}")


class RemoteConnectionNotOpenError(RemoteConnectionError):
	"""
	Raised when a remote connection is not open.

	:param connection_str: A connection string used to identify the connection being made.
	"""
	def __init__(self, connection_str):
		super().__init__(str(connection_str), "Connection is not open")


class RemoteConnectionCommandError(RemoteConnectionError):
	"""
	Raised when a remote connection command has failed.

	:param connection_str: A connection string used to identify the connection being made.
	:param response: The `Response` object for the failed command.
	"""
	def __init__(self, connection_str, response):
		super().__init__(str(connection_str), f"Command failed: {str(response)}")


class RemoteFileNotFoundError(RemoteConnectionError):
	"""
	Raised when a remote file or directory is not found.

	:param connection_str: A connection string used to identify the connection being made.
	:param path: The path to the remote file or directory.
	"""
	def __init__(self, connection_str, path):
		super().__init__(str(connection_str), f"File or directory {path} not found")


class RemoteFileExistsError(RemoteConnectionError):
	"""
	Raised when a remote file or directory exists but was expected not to exist.

	:param connection_str: A connection string used to identify the connection being made.
	:param path: The path to the remote file or directory.
	"""
	def __init__(self, connection_str, path):
		super().__init__(str(connection_str), f"File or directory {path} already exists")


class RemoteNotADirectoryError(RemoteConnectionError):
	"""
	Raised when a path is not a directory when it was expected to be.

	:param connection_str: A connection string used to identify the connection being made.
	:param path: The path to the directory.
	"""
	def __init__(self, connection_str, path):
		super().__init__(str(connection_str), f"Path {path} is not a directory")


class RemoteIsADirectoryError(RemoteConnectionError):
	"""
	Raised when a path is a directory when it was expected not to be.

	:param connection_str: A connection string used to identify the connection being made.
	:param path: The path to the directory.
	"""
	def __init__(self, connection_str, path):
		super().__init__(str(connection_str), f"Path {path} is a directory")


class PromiseCanceledException(ESXiUtilsException):
	"""
	Raised when a canceled promise is later attempted to be resolved.
	"""
	def __init__(self):
		super().__init__("Promise was canceled.")


class PromiseResolvedException(ESXiUtilsException):
	"""
	Raised when a resolved promise is re-attempted to be resolved.
	"""
	def __init__(self):
		super().__init__("Promise was already resolved.")


class GuestToolsError(ESXiUtilsException):
	"""
	Raised when there is an issue with guest tools on a virtual machine.

	:param vm: The `VirtualMachine` object.
	:param reason: The reason for the error.
	"""
	def __init__(self, vm, reason):
		super().__init__(f"Guest tools error for {str(vm)}: {str(reason)}")


class VirtualMachineHardwareError(ESXiUtilsException):
	"""
	Raised when there is an issue related to a virtual machine's hardware.

	:param vm: The `VirtualMachine` object.
	:param reason: The reason for the error.
	"""
	def __init__(self, vm, reason):
		super().__init__(f"Virtual machine hardware error for {str(vm)}: {str(reason)}")


class VirtualMachineInvalidHardwareConfigurationError(ESXiUtilsException):
	"""
	Raised when there is an issue related to a virtual machine's hardware configuration.

	:param vm: The `VirtualMachine` object.
	:param reason: The reason for the error.
	"""
	def __init__(self, vm, reason):
		super().__init__(f"Invalid hardware configuration for {str(vm)}: {str(reason)}")


class VirtualMachineHardwareNotFoundError(ESXiUtilsException):
	"""
	Raised when there is an issue with finding a virtual machine's hardware.

	:param vm: The `VirtualMachine` object.
	:param hardware_type: The type of hardware that could not be found (e.g. CD-ROM)
	:param info: Additional information that is relevant to identifying the particular hardware searched for.
	"""
	def __init__(self, vm, hardware_type, info):
		super().__init__(f"Unable to find {hardware_type} for {str(vm)}: {str(info)}")


class VirtualMachineHardwareNotConnectableError(ESXiUtilsException):
	"""
	Raised when there is a device is not connectable but an attempt to connect/disconnect the device was made.

	:param vm: The `VirtualMachine` object.
	:param device: The device in question.
	"""
	def __init__(self, vm, device):
		super().__init__(f"Device {str(device)} on {str(vm)} is not connectable")


class VNCError(ESXiUtilsException):
	"""
	Raised when there is a error with a virtual machine's VNC connection or configuration.

	:param vm: The `VirtualMachine` object.
	:param reason: The reason for the error
	"""
	def __init__(self, vm, reason):
		super().__init__(f"VNC error for {str(vm)}: {str(reason)}")


class VNCNotEnabledError(VNCError):
	"""
	Raised when VNC was expected to be enabled on a virtual machine, but is not.

	:param vm: The `VirtualMachine` object.
	"""
	def __init__(self, vm):
		super().__init__(vm, "VNC is not enabled")


class FirewallError(ESXiUtilsException):
	"""
	Raised when there is a error with ESXi's firewall.

	:param obj: The firewall-related object for error (e.g. A ruleset object).
	:param reason: The reason for the error
	"""
	def __init__(self, obj, reason):
		super().__init__(f"ESXi firewall error for {str(obj)}: {str(reason)}")


class NetworkingError(ESXiUtilsException):
	"""
	Raised when there is an error with ESXi's networking.

	:param obj: The networking-related object for the error.
	:param reason: The reason for the error.
	"""
	def __init__(self, obj, reason):
		super().__init__(f"ESXi networking error for {str(obj)}: {str(reason)}")


class NetworkingObjectNotFoundError(NetworkingError):
	"""
	Raised when a networking object is not found

	:param obj_type: The type of the object.
	:param name: The name of the object
	"""
	def __init__(self, obj_type, name):
		super().__init__(f"{obj_type} \"{name}\"", "not found")


class ESXiAPIError(ESXiUtilsException):
	"""
	Raised when there is an error related to the underlying pyVmomi API.

	:param reason: The reason for the error.
	"""
	def __init__(self, reason):
		super().__init__(f"API error, reason: {str(reason)}")


class ESXiAPIObjectNotFoundError(ESXiAPIError):
	"""
	Raised when there is an error related to finding an object using the underlying pyVmomi API.

	:param obj_type: The type of the object to be found.
	:param reason: The reason for the error.
	"""
	def __init__(self, obj_type, reason):
		super().__init__(f"Unable to find object \"{str(obj_type)}\": {str(reason)}")


class MultipleHostSystemsFoundError(ESXiUtilsException):
	"""
	Raised when multiple 'host system' machines are found but only one was expected.
	
	:param host_systems: The available host systems to choose from as a 'child' system
	"""
	def __init__(self, host_systems):
		err_str = "Multiple host systems found but no 'child_hostname' was provided! Available child hostnames: "
		for hs in host_systems:
			err_str += hs.name + "\t"
		super().__init__(err_str)


class ChildLoginFailureError(ESXiUtilsException):
	"""
	Raised when 'child' HostSystem parameters are provided to connect to a server host under a vCenter system,
	but the login fails.
	
	:param child_hostname: The child server that login was attempted on
	:param child_username: The username on the child server that login was attempted on
	"""
	def __init__(self, child_hostname, child_username):
		err_str = f"Failed to login to child HostSystem: {child_hostname} using username: {child_username}! Check that you have a connection to the server and the login credentials are correct."
		super().__init__(err_str)


class MultipleFoldersFoundError(ESXiUtilsException):
	"""
	Raised when multiple 'folder' objects are found but only one was expected.
	
	:param folders: The available folders to choose from
	"""
	def __init__(self, folders):
		err_str = "Multiple folders found with same name but only one was expected: "
		for f in folders:
			err_str += "Name: " + f.name + " ... moId: " + f._moId + "\t"
		super().__init__(err_str)


class UsbScanCodeError(ESXiUtilsException):
	"""
	Raised when there is a error with sending keys to a virtual machine.

	:param vm: The `VirtualMachine` object.
	:param reason: The reason for the error
	"""
	def __init__(self, vm, reason):
		super().__init__(f"UsbScanCodeError error for {str(vm)}: {str(reason)}")


class UsbScanCodeModifierError(ESXiUtilsException):
	"""
	Raised on attempting an application of an invalid modifier to a USB scan code key.

	:param reason: The reason for the error
	"""
	def __init__(self, reason):
		super().__init__(f"UsbScanCodeModifierError error: {str(reason)}")


class ScreenshotError(ESXiUtilsException):
	"""
	Raised when there is a error with taking a screenshot of a virtual machine.

	:param vm: The `VirtualMachine` object.
	:param reason: The reason for the error
	"""
	def __init__(self, vm, reason):
		super().__init__(f"ScreenshotError error for {str(vm)}: {str(reason)}")

class RenameError(ESXiUtilsException):
	"""
	Raised when there is a error with renaming a virtual machine.

	:param vm: The `VirtualMachine` object.
	:param reason: The reason for the error
	"""
	def __init__(self, vm, reason):
		super().__init__(f"RenameError error for {str(vm)}: {str(reason)}")
