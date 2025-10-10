from esxi_utils.util import log, exceptions
from lxml import etree
import pyVmomi
import typing
import re

if typing.TYPE_CHECKING:
	from esxi_utils.firewall.firewall import Firewall
	from esxi_utils.firewall.ruleset import Ruleset

class RuleList:
	"""
	List of rules for a ruleset on the host firewall.
	"""
	def __init__(self, ruleset: 'Ruleset'):
		self._ruleset = ruleset

	def __iter__(self) -> typing.Iterator['Rule']:
		return iter([ Rule(self._ruleset, obj) for obj in self._ruleset._obj.rule ])

	def __getitem__(self, index) -> 'Rule':
		return self.items[index]

	@property
	def items(self) -> typing.List['Rule']:
		"""
		A list of all items
		"""
		return list(self)

	def add(self, direction: str, protocol: str, porttype: str, begin: str, end: typing.Optional[str] = None) -> 'Rule':
		"""
		Add a new rule to this ruleset.
		
		:param direction: The new rule's direction (i.e. 'outbound' or 'inbound').
		:param protocol: The new rule's protocol (i.e. 'tcp' or 'udp')
		:param porttype: The new rule's port type (i.e. 'src' or 'dst')
		:param begin: The new rule's begin port.
		:param end: The new rule's end port. If `None`, this rule will only apply to the port denoted by `begin`.

		:return: The newly added `Rule` object
		"""
		assert direction in ["outbound", "inbound"], "direction must be either 'outbound' or 'inbound'"
		assert protocol in ["tcp", "udp"], "protocol must be either 'tcp' or 'udp'"
		assert porttype in ["src", "dst"], "porttype must be either 'src' or 'dst'"
		assert isinstance(begin, int) and begin > 0 and begin <= 65535, "begin must be a integer in range 1-65535"
		assert end is None or (isinstance(end, int) and end > 0 and end <= 65535 and end >= begin), "end must be a integer in range 1-65535 and greater or equal to begin, or None"
		rule_str = f"{direction} {porttype} {str(begin) + '-' + str(end) if end else str(begin)} {protocol}"
		log.info(f"{str(self)} Adding new rule: \"{rule_str}\"")

		def get_matching():
			results = [ rule for rule in self if rule.direction == direction and rule.protocol == protocol and rule.porttype == porttype and rule.port == begin and rule.endport == end ]
			if len(results) == 0:
				return None
			return results[0]

		# Ensure this rule doesn't exist
		if get_matching():
			raise exceptions.FirewallError(self, f"Rule \"{rule_str}\" already exists")

		# Find the ruleset
		tree, existing_ruleset_tag = self._ruleset._get_xml_ruleset()
		existing_rule_elements = existing_ruleset_tag.findall("./rule")
		
		# Re-create the ruleset element
		# To ensure this is properly formatted, as rulesets may be formatted differently (i.e. without rule IDs)
		# we'll just completely re-create this service element by copying over old information alongside the newly added rule
		new_ruleset_tag = etree.Element("service")
		new_ruleset_tag.set("id", existing_ruleset_tag.get("id"))
		etree.SubElement(new_ruleset_tag, "id").text = existing_ruleset_tag.find("./id").text

		new_rule_tag = etree.Element("rule")
		etree.SubElement(new_rule_tag, "direction").text = direction
		etree.SubElement(new_rule_tag, "protocol").text = protocol
		etree.SubElement(new_rule_tag, "porttype").text = porttype

		if end:
			port_tag = etree.SubElement(new_rule_tag, "port")
			etree.SubElement(port_tag, "begin").text = str(begin)
			etree.SubElement(port_tag, "end").text = str(end)
		else:
			etree.SubElement(new_rule_tag, "port").text = str(begin)

		for i, rule in enumerate([*existing_rule_elements, new_rule_tag]):
			rule.set("id", str(i).zfill(4))
			new_ruleset_tag.append(rule)

		etree.SubElement(new_ruleset_tag, "enabled").text = existing_ruleset_tag.find("./enabled").text
		etree.SubElement(new_ruleset_tag, "required").text = existing_ruleset_tag.find("./required").text
		
		# Overwrite the existing ruleset
		tree.replace(existing_ruleset_tag, new_ruleset_tag)
		self._ruleset._firewall._update_service_xml(tree)

		# Get the newly added rule
		matching = get_matching()
		if matching is None:
			raise exceptions.FirewallError(self, f"Failed to get newly added rule \"{rule_str}\"")
		return matching

	def __str__(self):
		return f"<{type(self).__name__} for Ruleset {self._ruleset.key} ({len(self.items)} rules)>"

	def __repr__(self):
		return str(self)


class Rule:
	"""
	A Firewall Rule.
	"""
	def __init__(self, ruleset: 'Ruleset', rule_obj: pyVmomi.vim.host.Ruleset.Rule):
		self._ruleset = ruleset
		self._obj = rule_obj

	@property
	def port(self) -> int:
		"""
		The firewall rule port number or start port.
		"""
		return self._obj.port

	@property
	def endport(self) -> typing.Union[int, None]:
		"""
		For a port range, the ending port number. 
		"""
		return self._obj.endPort

	@property
	def range(self) -> str:
		"""
		The port range as a string if this rule defines a range, otherwise just the port this rule defines.
		"""
		return f"{self.port}-{self.endport}" if self.endport else str(self.port)

	@property
	def direction(self) -> str:
		"""
		The port direction.
		"""
		return self._obj.direction

	@property
	def porttype(self) -> str:
		"""
		The firewall rule port type.
		"""
		return self._obj.portType

	@property
	def protocol(self) -> str:
		"""
		The firewall rule protocol.
		"""
		return self._obj.protocol

	def remove(self):
		"""
		Remove this rule from its parent ruleset.
		"""
		tree, ruleset, rule = self._get_xml_rule()
		ruleset.remove(rule)
		for i, rule in enumerate(ruleset.findall(f"./rule")): # Re-write the IDs to ensure they are correctly ordered
			rule.set("id", str(i).zfill(4))
		self._ruleset._firewall._update_service_xml(tree)

	def _get_xml_rule(self):
		"""
		Get this rule from /etc/vmware/firewall/service.xml as an `etree.Element` object.

		:return: A tuple (tree, ruleset element, rule element)
		"""
		tree, ruleset = self._ruleset._get_xml_ruleset()
		for rule in ruleset.findall(f"./rule"):
			direction = rule.find("./direction").text if rule.find("./direction") is not None else None
			porttype = rule.find("./porttype").text if rule.find("./porttype") is not None else None
			protocol = rule.find("./protocol").text if rule.find("./protocol") is not None else None
			port = rule.find("./port").text if rule.find("./port") is not None else None
			begin = rule.find("./port/begin").text if rule.find("./port/begin") is not None else None
			endport = rule.find("./port/end").text if rule.find("./port/end") is not None else None
			port = begin or port
			if direction != self.direction or porttype != self.porttype or protocol != self.protocol or str(port) != str(self.port) or str(endport) != str(self.endport):
				continue
			return (tree, ruleset, rule)
		raise exceptions.FirewallError(self, f"Failed to find rule in /etc/vmware/firewall/service.xml")

	def __str__(self):
		return f"<Rule {self.direction} {self.porttype} {self.range} {self.protocol}>"

	def __repr__(self):
		return str(self)