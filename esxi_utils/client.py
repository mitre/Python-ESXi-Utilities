from esxi_utils.vm.virtualmachine import VirtualMachineList
from esxi_utils.util.connect.esxi import ESXiSSHConnection
from esxi_utils.networking.physicalnic import PhysicalNICList
from esxi_utils.networking.vmkernelnic import VMKernelNICList
from esxi_utils.networking.portgroup import PortGroupList
from esxi_utils.networking.distributedportgroup import DistributedPortGroupList
from esxi_utils.networking.vswitch import VSwitchList
from esxi_utils.networking.distributedvswitch import DistributedVSwitchList
from esxi_utils.datastore import DatastoreList
from esxi_utils.util import log, exceptions
from esxi_utils.firewall.firewall import Firewall
from pyVim.connect import SmartConnect, Disconnect
from contextlib import contextmanager
import threading
import pyVmomi
import typing
import time
import ssl

class ESXiClient:
	"""
	Client object for an ESXi host. Provides functionality for working with an ESXi host, such as querying
	for datastores, virtual machines, vswitches, and more.

	Typical usage of this package begins with initializing this client object and retrieving the desired objects
	through the provided API of this class.

	:param hostname: The hostname or IP of the ESXi server.
	:param username: The username for connecting over SSH.
	:param password: The password for connecting over SSH.
	:param child_hostname: When connecting to a vCenter instance, the hostname or IP of the child ESXi server.
	:param child_username: When connecting to a vCenter instance, the username to login to the child ESXi server (for SSH).
	:param child_password: When connecting to a vCenter instance, the password of the child ESXi user.
	"""
	def __init__(self, hostname: str, username: str, password: str, child_hostname: typing.Optional[str] = None, child_username: typing.Optional[str] = None, child_password: typing.Optional[str] = None):
		context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
		context.verify_mode = ssl.CERT_NONE
		err = None
		try:
			self._service_instance = SmartConnect(
				host=hostname,
				user=username, 
				pwd=password, 
				sslContext=context
			)
		except TimeoutError:
			err = TimeoutError(f"Connection timed out while attempting to connect to ESXi server at {hostname}. Check the correctness of the hostname and that the ESXi server is reachable.")
		except Exception as e:
			if "vim.fault.InvalidLogin" in str(e):
				err = ConnectionError(f"Cannot login to ESXi server at {hostname} as user \"{username}\" due to an incorrect user name or password.")
			else:
				err = e
		if err:
			raise err
		self._vcenter_hostname = hostname
		self._child_hostname = child_hostname
		self._child_username = child_username
		self._child_password = child_password
		self._host_system = None
		self._child_esxi_client_instance = None
		self._all_host_systems = self._get_vim_objects(pyVmomi.vim.HostSystem)
		self._host_system = self._find_host_system()
		if self._child_hostname and self._child_username and self._child_password:
			self._hostname = self._host_system.name
			try:
				self._child_esxi_client_instance = ESXiClient(self._child_hostname, self._child_username, self._child_password)
			except Exception as e:
				raise exceptions.ChildLoginFailureError(self._child_hostname, self._child_username)
		else:
			self._hostname = hostname
		self._username = username
		self._password = password
		self._keepalive = _ESXiClientKeepAlive(self)
		self._keepalive.start()
		log.info(f"{str(self)} Created.")
	
	def __enter__(self):
		return self
	
	def __exit__(self, *args):
		self.close()

	def close(self):
		"""
		Close the connection to this host.
		"""
		if hasattr(self, "_keepalive") and self._keepalive:
			self._keepalive.stop()
			self._keepalive.join()
		Disconnect(self._service_instance)
		if self._child_esxi_client_instance:
			self._child_esxi_client_instance.close()
	
	@property
	def hostname(self) -> str:
		"""
		The hostname for this ESXiClient.
		"""
		return self._hostname

	@property
	def username(self) -> str:
		"""
		The username for this ESXiClient.
		"""
		return self._username

	@property
	def password(self) -> str:
		"""
		The password for this ESXiClient.
		"""
		return self._password

	@property
	def vms(self) -> 'VirtualMachineList':
		"""
		The Virtual Machine handler for this host.
		"""
		return VirtualMachineList(self)

	@property
	def firewall(self) -> 'Firewall':
		"""
		The Firewall for this host.
		"""
		return Firewall(self)

	@property
	def datastores(self) -> 'DatastoreList':
		"""
		List of datastores on this host.
		"""
		return DatastoreList(self)
	
	@property
	def vswitches(self) -> 'VSwitchList':
		"""
		List of virtual switches on this host.
		"""
		return VSwitchList(self)
	
	@property
	def distributed_vswitches(self) -> 'DistributedVSwitchList':
		"""
		List of distributed virtual switches on this host.
		"""
		return DistributedVSwitchList(self)

	@property
	def portgroups(self) -> 'PortGroupList':
		"""
		List of port groups on this host.
		"""
		return PortGroupList(self)

	@property
	def distributed_portgroups(self) -> 'DistributedPortGroupList':
		"""
		List of distributed port groups on this host.
		"""
		return DistributedPortGroupList(self)
	
	@property
	def physicalnics(self) -> 'PhysicalNICList':
		"""
		List of physical NICs on this host.
		"""
		return PhysicalNICList(self)

	@property
	def vmkernelnics(self) -> 'VMKernelNICList':
		"""
		List of VMKernel NICs on this host.
		"""
		return VMKernelNICList(self)
	
	@property
	def hostNumCpuCores(self) -> int:
		"""
		The number of CPU cores that this ESXi server host has
		"""
		return self._host_system.hardware.cpuInfo.numCpuCores
	
	@property
	def hostCpuHz(self) -> int:
		"""
		The (clock?) speed of this ESXi server host's CPU cores
		"""
		return self._host_system.hardware.cpuInfo.hz
	
	def total_available_cpu_usage(self, unit: str = "MHz") -> float:
		"""
		Get the total available CPU capacity in the provided unit.
		The formula used for this is: (number of CPU cores total) * (core Speed in HZ) // ( 10^[3 *(unit_power)] )

		:param unit: The unit of measurement to use (one of: Hz, KHz, MHz, GHz).

		:return: The total amount of CPU capacity in the provided unit.
		"""
		hz_unit_orders = ["Hz", "KHz", "MHz", "GHz"]
		return self.hostNumCpuCores * self.hostCpuHz / 10**(3*hz_unit_orders.index(unit))

	def current_cpu_usage(self, unit: str = "MHz") -> float:
		"""
		Get the current CPU usage in the provided unit.

		:param unit: The unit of measurement to use (one of: Hz, KHz, MHz, GHz).

		:return: The current CPU usage in the provided unit.
		"""
		hz_unit_orders = ["Hz", "KHz", "MHz", "GHz"]
		return self._host_system.summary.quickStats.overallCpuUsage * 1000 * 1000 / 10**(3*hz_unit_orders.index(unit))
	
	def total_available_memory(self, unit: str = "B") -> float:
		"""
		Get the total amount of memory (RAM) installed on this ESXi host in the provided unit.
		
		:param unit: The unit of measurement to use (one of: B, KB, MB, GB, TB).

		:return: The total amount of memory (RAM) installed on this ESXi host.
		"""
		unit_orders = ["B", "KB", "MB", "GB", "TB"]
		assert unit in unit_orders, f"unit must be one of: {', '.join(unit_orders)}"
		# The API returns this in bytes
		return self._host_system.hardware.memorySize / pow(1024, unit_orders.index(unit))
	
	def current_memory_usage(self, unit: str = "B") -> float:
		"""
		Get the current amount of memory (RAM) in use on this ESXi host in the provided unit.
		
		:param unit: The unit of measurement to use (one of: B, KB, MB, GB, TB).

		:return: The current amount of memory (RAM) in use on this ESXi host.
		"""
		unit_orders = ["B", "KB", "MB", "GB", "TB"]
		assert unit in unit_orders, f"unit must be one of: {', '.join(unit_orders)}"
		# The API returns this quickStat in MB
		return self._host_system.summary.quickStats.overallMemoryUsage * 1024 * 1024 / pow(1024, unit_orders.index(unit))

	def memory_usage_percent(self) -> float:
		"""
		Returns the percentage usage of the RAM of the server
		"""
		return self.current_memory_usage() / self.total_available_memory()

	def cpu_usage_percent(self) -> float:
		"""
		Returns the percentage usage of the CPUs of the server 
		"""
		return self.current_cpu_usage() / self.total_available_cpu_usage()

	@contextmanager
	def ssh(self, force_parent: bool = False) -> typing.Generator['ESXiSSHConnection', None, None]:
		"""
		Connect to the underlying ESXi host over SSH. Yields a `UnixSSHConnection` object.

		:param force_parent:
			When connected to a vCenter system and this value is set to True:
			Will SSH into the vCenter hostname instead of the (default) child HostSystem hostname
			Authenication will fail if you do not have an account on the vCenter server.
		"""
		if force_parent:
			ip = self._vcenter_hostname
			user = self.username
			pw = self.password
		else:
			ip = self.hostname
			user = self._child_username if self._child_username is not None else self.username
			pw = self._child_password if self._child_password is not None else self.password
		with ESXiSSHConnection(ip=ip, username=user, password=pw) as conn:
			yield conn

	def __str__(self):
		return f"<{type(self).__name__} for {self.username}@{self.hostname}>"

	def __repr__(self):
		return str(self)

	def __del__(self):
		self.close()

	def _get_vim_objects_from(self, root, vim_type):
		"""
		Search the ESXi server for the all instances of the specified vim object under the given root object.

		:param root: The root object to search.
		:param vim_type: The vim type of the objects to get (e.g. pyVmomi.vim.VirtualMachine)

		:return: A list of all vim objects.
		"""
		if not isinstance(vim_type, list):
			vim_type = [vim_type]
		content = self._service_instance.RetrieveContent()
		container = content.viewManager.CreateContainerView(root, vim_type, True)
		objs = [ ref for ref in container.view ]
		container.Destroy()
		return objs

	def _get_vim_objects(self, vim_type, query_root: bool = False):
		"""
		Search the ESXi server for the all instances of the specified vim object.

		:param vim_type: The vim type of the objects to get (e.g. pyVmomi.vim.VirtualMachine)
		:param query_root: When True: Search from the 'root' Folder of ESXi instead of from the current 'host_system'

		:return: A list of all vim objects.
		"""
		# request only content based on the currently connected 'host_system' server
		if not query_root and self._child_hostname and self._host_system:
			return self._get_vim_objects_from(self._host_system, vim_type)
		return self._get_vim_objects_from(self._service_instance.RetrieveContent().rootFolder, vim_type)

	def _get_vim_object(self, vim_type, name: str):
		"""
		Search the ESXi server for the specified vim object.

		:param vim_type: The vim type of the object to get (e.g. pyVmomi.vim.VirtualMachine)
		:param name: The name of the object to get.

		:return: The vim object. Raises a RuntimeException if the object was not found, or if multiple we found.
		"""
		objs = self._get_vim_objects(vim_type)
		found = [ ref for ref in objs if ref.name == name ]
		if len(found) == 0:
			raise exceptions.ESXiAPIObjectNotFoundError(vim_type, f"{name} not found")
		elif len(found) > 1:
			raise exceptions.ESXiAPIObjectNotFoundError(vim_type, f"Multiple instances of {name} found")
		return found[0]

	def _get_network_object_from_host_system(self, name: str):
		"""
		Search the ESXi 'HostSystem' for the specified network object.
		This function specifically searches the HostSystem and not the 'root ServiceManager'.
		( Also see _get_vim_object() )

		:param name: The name of the object to get.

		:return: The vim object. Raises a RuntimeException if the object was not found, or if multiple we found.
		"""
		objs = self._get_network_objects_from_host_system()
		found = [ ref for ref in objs if ref.name == name ]
		if len(found) == 0:
			raise exceptions.ESXiAPIObjectNotFoundError(pyVmomi.vim.Network, f"{name} not found")
		elif len(found) > 1:
			raise exceptions.ESXiAPIObjectNotFoundError(pyVmomi.vim.Network, f"Multiple instances of {name} found")
		return found[0]

	def _get_network_objects_from_host_system(self):
		"""
		Returns the network objects associated with the connected 'HostSystem' object.

		:return: 'pyVmomi.VmomiSupport.ManagedObject[]' instance of managed network objects
		"""
		return self._host_system.network

	def _get_datastore_objects_from_host_system(self):
		"""
		Returns the datastore objects associated with the connected 'HostSystem' object.

		:return: 'pyVmomi.VmomiSupport.ManagedObject[]' instance of managed datastore objects
		"""
		return self._host_system.datastore

	def _wait_for_task(self, task):
		"""
		Wait for a `vim.Task` to complete.

		:param task: The `vim.Task` object to wait for.

		:return: The task result. If the task exits with status 'error', a exception will be thrown.
		"""
		assert isinstance(task, pyVmomi.vim.Task)
		while task.info.state not in [pyVmomi.vim.TaskInfo.State.error, pyVmomi.vim.TaskInfo.State.success]:
			time.sleep(0.2)
		if task.info.state == pyVmomi.vim.TaskInfo.State.error:
			raise exceptions.ESXiAPIError(str(task.info))
		return task.info.result

	def _find_host_system(self):
		"""
		Finds the correct 'HostSystem' to use based the 'child_hostname' param provided to init.
		If no 'child_hostname' is provided and there are multiple options, an ESXiAPIObjectNotFoundError is thrown.
		Otherwise, returns the only 'HostSystem' that exists.

		:return: the underlying host system to use
		"""
		# not a vCenter or no child hostname was specified
		if self._child_hostname is None:
			if isinstance(self._all_host_systems, list):
				if len(self._all_host_systems) > 1:
					raise exceptions.MultipleHostSystemsFoundError(self._all_host_systems)
				return self._all_host_systems[0]
			return self._all_host_systems
		# find the specified host system
		for esxi_server in self._all_host_systems:
			if self._child_hostname == esxi_server.name:
				return esxi_server
		# that hostname could not be found
		raise exceptions.ESXiAPIObjectNotFoundError('pyVmomi.vim.HostSystem', f"{self._child_hostname} child hostname not found")
# end ESXi client class

		
class _ESXiClientKeepAlive(threading.Thread):
	"""
	Class for keeping an ESXi client alive.

	:param client: An `ESXiClient` object
	"""
	def __init__(self, client):
		threading.Thread.__init__(self, daemon=True)
		assert isinstance(client, ESXiClient)
		self.service_instance = client._service_instance
		self.id = str(client)
		self.running = True

	def stop(self):
		"""
		Stop the keep-alive thread.
		"""
		self.running = False
	
	def run(self):
		i = 0
		while self.running:
			time.sleep(1)
			i += 1
			if i == 300:
				self.service_instance.CurrentTime()
				i = 0
			