from esxi_utils.util import log, exceptions
from lxml import etree
import typing

if typing.TYPE_CHECKING:
	from esxi_utils.firewall.firewall import Firewall
	from esxi_utils.firewall.rule import RuleList

class RulesetList:
	"""
	List of Rulesets for the host firewall.
	"""
	def __init__(self, firewall: 'Firewall'):
		self._firewall = firewall

	def __iter__(self) -> typing.Iterator['Ruleset']:
		return iter([ Ruleset(self._firewall, obj.key) for obj in self._firewall._firewall_info.ruleset ])

	def __getitem__(self, name) -> 'Ruleset':
		return self.get(name)

	def __contains__(self, name: str) -> bool:
		return self.exists(name)

	@property
	def items(self) -> typing.List['Ruleset']:
		"""
		A list of all items
		"""
		return list(self)

	def find(self, key: str) -> typing.Union['Ruleset', None]:
		"""
		Get a ruleset by key.

		:param key: The ruleset key to search for.

		:return: The `Ruleset` object, or `None` if not found.
		"""
		found = [ ruleset for ruleset in self if ruleset.key == key ]
		if len(found) == 0:
			return None
		return found[0]

	def get(self, key: str) -> 'Ruleset':
		"""
		Get a ruleset by key and raise an exception if not found.

		:param key: The ruleset key to search for.

		:return: The `Ruleset` object
		"""
		ruleset = self.find(key)
		if ruleset is None:
			raise exceptions.FirewallError(self, f"No ruleset found with key '{key}'")
		return ruleset

	def exists(self, key: str) -> bool:
		"""
		Check whether a ruleset exists.

		:parma key: The ruleset key

		:return: Whether or not the ruleset exists
		"""
		return self.find(key) is not None

	def add(self, key: str, enabled: str = True, required: str = False) -> 'Ruleset':
		"""
		Add a firewall ruleset. If this ruleset already exists, an error will be raised.

		:param key: The new ruleset's key.
		:param enabled: Whether or not this ruleset should be enabled.
		:param required: Whether or not this ruleset is required.

		:return: A `Ruleset` object for the new ruleset.
		"""
		assert isinstance(key, str), "key must be a string"
		assert isinstance(enabled, bool), "enabled must be a boolean"
		assert isinstance(required, bool), "required must be a boolean"

		log.info(f"{str(self)} Adding new ruleset: {key}")
		if self.exists(key):
			raise exceptions.FirewallError(self, f"A ruleset already exists with key '{key}'")

		tree = self._firewall._get_service_xml()

		# Find the next available number ID for the ruleset
		# Rulesets are numbered by a unique 4-digit ID (in addition to their "text" ID)
		# We find the highest currently on the firewall and then add 1
		ids = []
		for node in tree.findall("./service"):
			ids.append(int(node.get("id")))
		max_id = max(ids)
		if max_id >= 9999:
			raise exceptions.FirewallError(self, f"Maximum ruleset ID reached ({max_id})")
		next_id = str(max_id+1).zfill(4)
		log.debug(f"Next available ruleset ID: {next_id}")

		# Create the service node and add comments
		service_tag = etree.SubElement(tree, "service")
		service_tag.set("id", next_id)
	
		# Add the "text" id tag to this ruleset
		id_tag = etree.SubElement(service_tag, "id")
		id_tag.text = key
		
		# Add remaining tags to ruleset
		enabled_tag = etree.SubElement(service_tag, "enabled")
		enabled_tag.text = "true" if enabled else "false"

		required_tag = etree.SubElement(service_tag, "required")
		required_tag.text = "true" if required else "false"

		self._firewall._update_service_xml(tree)
		# on vCenter the connection may get messed up during firewall refresh.
		# try to find the key in the child server
		if self._firewall._client._child_hostname:
			log.error('WARN: Enabling VNC in a vCenter instance may cause communication errors! Manually reset the server to green and "connect" it in vCenter.')
			return self._firewall._client._child_esxi_client_instance.firewall.rulesets.get(key)
		return self.get(key)

	def enable_vnc(self) -> 'Ruleset':
		"""
		Add a ruleset for VNC access.

		:return: The created VNC ruleset.
		"""
		ruleset = self.add("VNC", enabled=True, required=False)
		ruleset.rules.add(direction="inbound", protocol="tcp", porttype="dst", begin=5900, end=6000)
		return ruleset

	def __str__(self):
		return f"<{type(self).__name__} for {self._firewall._client.hostname} ({len(self.items)} rulesets)>"

	def __repr__(self):
		return str(self)


class Ruleset:
	"""
	Class for an ESXi firewall ruleset.
	"""
	def __init__(self, firewall: 'Firewall', key: str):
		self._firewall = firewall
		self._key = key

	@property
	def key(self) -> str:
		"""
		The ruleset key.
		"""
		return self._key

	@property
	def label(self) -> str:
		"""
		Display label for the ruleset.
		"""
		return self._obj.label

	@property
	def service(self) -> str:
		"""
		Managed service (if any) that uses this ruleset.
		"""
		return self._obj.service

	@property
	def enabled(self) -> bool:
		"""
		Flag indicating whether the ruleset is enabled.
		"""
		return self._obj.enabled

	@property
	def rules(self) -> 'RuleList':
		"""
		List of rules within the ruleset.
		"""
		from esxi_utils.firewall.rule import RuleList
		return RuleList(self)

	def remove(self):
		"""
		Remove this ruleset from its parent firewall.
		"""
		tree, ruleset = self._get_xml_ruleset()
		ruleset.getparent().remove(ruleset)
		self._firewall._update_service_xml(tree)

	def _get_xml_ruleset(self):
		"""
		Get this ruleset from /etc/vmware/firewall/service.xml as an `etree.Element` object.

		:return: A tuple (tree, element)
		"""
		tree = self._firewall._get_service_xml()
		found = tree.find(f"./service[id='{self.key}']") 
		if found is None:
			raise exceptions.FirewallError(self, f"Failed to find ruleset in /etc/vmware/firewall/service.xml")
		return (tree, found)

	@property
	def _obj(self):
		for obj in self._firewall._firewall_info.ruleset:
			if obj.key == self.key:
				return obj
		raise exceptions.FirewallError(self, f"No ruleset found with key '{self.key}'")

	def __str__(self):
		return f"<Ruleset key='{self.key}' label='{self.label}' service='{self.service}' enabled='{self.enabled}' ({len(self.rules.items)} rules)>"

	def __repr__(self):
		return str(self)