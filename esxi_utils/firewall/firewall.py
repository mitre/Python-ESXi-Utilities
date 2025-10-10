from esxi_utils.firewall.ruleset import RulesetList
from esxi_utils.util import log
import concurrent.futures
from lxml import etree
import typing
import socket
import re

if typing.TYPE_CHECKING:
	from esxi_utils.client import ESXiClient

class Firewall:
	"""
	The host firewall.
	"""
	def __init__(self, client: 'ESXiClient'):
		self._client = client

	@property
	def default_policy(self) -> typing.Dict[str, bool]:
		"""
		The default firewall policy. A dict containing the keys `IncomingBlocked` and `OutgoingBlocked`
		"""
		return {"IncomingBlocked": self._firewall_info.defaultPolicy.incomingBlocked, "OutgoingBlocked": self._firewall_info.defaultPolicy.outgoingBlocked}

	@property 
	def rulesets(self) -> 'RulesetList':
		"""
		Rulesets for the firewall.
		"""
		return RulesetList(self)

	def find_vnc_port(self) -> typing.List[int]:
		"""
		Detect an open VNC port on the ESXi host. VNC ports must be used by one VM only, and must be exposed by firewall rules (ports 5900-6000).
		This function will attempt to detect available ports by sequentially connecting to each within the VNC port range. 
		If a port is found, it is advised to assign the port to a VM immediately to avoid another VM from acquiring the same port.

		:return: A list of ints (valid VNC ports)
		"""
		log.info(f"Searching for VNC port...")

		# This process is derived from the process used by the Packer VMware plugin
		# Process ports ESXi is listening on to determine which are available
		# This process does best effort to detect ports that are unavailable,
		# it will ignore any ports listened to by only localhost
		with self._client.ssh() as conn:
			ip_data_list = conn.esxcli("network ip connection list")
		listen_ports = dict()
		for record in ip_data_list:
			if record["State"] == "LISTEN":
				split_address = record["LocalAddress"].split(":")
				if split_address[0] != "127.0.0.1":
					listen_ports[int(split_address[-1])] = True
		
		def thread_func(test_port):
			nonlocal listen_ports
			if test_port in listen_ports:
				log.debug(f"VNC Port {test_port} in use.")
				return None # In use
			s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			s.settimeout(10)
			try:
				s.connect((self._client.hostname, test_port))
			except Exception as e:
				if "timed out" not in str(e).lower():
					log.debug(f"VNC Port {test_port} valid.")
					return test_port
				else:
					log.debug(f"VNC Port {test_port} unavailable ({str(e)}).")
			finally:
				s.close()
			return None
		
		valid_ports = []
		with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
			futures = []
			for port in range(5900, 6001):
				futures.append(executor.submit(thread_func, port))
			for future in concurrent.futures.as_completed(futures):
				valid = future.result()
				if valid:
					valid_ports.append(valid)
			
		return valid_ports
		
	def _get_service_xml(self):
		"""
		Get the contents of /etc/vmware/firewall/service.xml as an `etree` object.
		"""
		with self._client.ssh() as conn:
			service_xml = conn.read("/etc/vmware/firewall/service.xml")
		return etree.fromstring(service_xml, parser=etree.XMLParser(remove_blank_text=True))

	def _update_service_xml(self, new_tree):
		"""
		Update /etc/vmware/firewall/service.xml with new content

		:param new_tree: The `etree` XML object to write to the service file.
		"""
		new_content = etree.tostring(new_tree, pretty_print=True, encoding='unicode')
		new_content = re.sub(r"</service>", "\g<0>\n", new_content, flags=re.MULTILINE)
		with self._client.ssh() as conn:
			err = None
			try:
				# See: https://kb.vmware.com/s/article/2008226
				conn.exec("chmod 644 /etc/vmware/firewall/service.xml")
				conn.exec("chmod +t /etc/vmware/firewall/service.xml")
				conn.write("/etc/vmware/firewall/service.xml", new_content, overwrite=True)
				conn.exec("esxcli network firewall refresh", assert_status=0)
			except Exception as e:
				err = e
			finally:
				conn.exec("chmod 444 /etc/vmware/firewall/service.xml")
				conn.exec("chmod +t /etc/vmware/firewall/service.xml")
			if err:
				raise err

	@property
	def _firewall_system(self):
		return self._client._host_system.configManager.firewallSystem

	@property
	def _firewall_info(self):
		return self._firewall_system.firewallInfo

	def __str__(self):
		return f"<{type(self).__name__} for {self._client.hostname}>"

	def __repr__(self):
		return str(self)