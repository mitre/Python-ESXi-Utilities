from re import L
from lxml import etree
import typing

class XmlFile:
	"""
	Proxy class for working with an XML file.
	"""
	def __init__(self, file, update_callback: typing.Optional[typing.Callable[[str], None]] = None):
		parser = etree.XMLParser(remove_blank_text=True)
		self._tree = etree.parse(file, parser)
		self._update_callback = update_callback

	def update(self):
		if self._update_callback and callable(self._update_callback):
			self._update_callback(self.xml(pretty_print=True, xml_declaration=True))

	def xml(self, pretty_print: bool = True, xml_declaration: bool = False) -> str:
		"""
		Dump the current XML tree to a string representation.

		:param pretty_print: Whether or not to pretty print the XML.
		:param xml_declaration: Whether or not to include the XML declaration.

		:return: The XML string for this node.
		"""
		return etree.tostring(self._tree, encoding="utf-8", pretty_print=pretty_print, xml_declaration=xml_declaration, with_comments=True).decode("utf-8").strip()

	@property
	def root(self):
		return _XmlElement(self._tree.find("."), self)

	def __str__(self):
		return self.xml()

	def __repr__(self):
		return f"<{type(self).__name__} at {self._tree.docinfo.URL}>"
		

class _XmlElement:
	"""
	Proxy class for working with an element of an XML file.
	"""
	def __init__(self, element: 'etree._Element', file: 'XmlFile'):
		assert isinstance(element, etree._Element), "element is not an element"
		self._element = element
		self._file = file

	@property
	def tag(self) -> str:
		namespaces = self._element.nsmap
		prefix = self._element.prefix
		tag = self._element.tag
		if prefix not in namespaces:
			return tag
		uri = namespaces[prefix]
		base = tag[len("{"+uri+"}"):]
		if not prefix:
			return base
		return f"{prefix}:{base}"

	@property
	def children(self) -> typing.List['_XmlElement']:
		return [ _XmlElement(child, self._file) for child in self._element ]

	@property
	def attributes(self) -> '_XmlAttributes':
		return _XmlAttributes(self)

	@property
	def text(self) -> typing.Union[str, None]:
		return self._element.text

	@text.setter
	def text(self, value):
		self._element.text = value
		self._file.update()

	@property
	def summary(self) -> typing.Dict[str, typing.Any]:
		return { "tag": self.tag, "attributes": self.attributes, "text": self.text }
	
	def find(self, tag: str) -> typing.List['_XmlElement']:
		"""
		Find all children matching the given tag name.

		:param tagname: The name of the tag for the child to get.

		:return: A list of `_XmlElement` elements
		"""
		return [ child for child in self.children if child.tag == tag ]

	def get(self, tag: str) -> '_XmlElement':
		"""
		Get the first child matching the given tag name. Raises an exception if the child was not found.

		:param tag: The name of the tag for the child to get.

		:return: An `_XmlElement` element
		"""
		matched = self.find(tag)
		if len(matched) == 0:
			raise KeyError(f"child tag '{tag}' not found")
		return matched[0]

	def append(self, tag: str) -> '_XmlElement':
		"""
		Create a new child element at the end of this element's children.

		:param tag: The name of the new tag to add.

		:return: An `_XmlElement` element for the new child
		"""
		for ns, uri in self._element.nsmap.items():
			if ns is None:
				continue
			prefix = f"{ns}:"
			if tag.startswith(prefix):
				base = tag[len(prefix):]
				tag = "{" + uri + "}" + base
		el = etree.SubElement(self._element, tag)
		self._file.update()
		return _XmlElement(el, self._file)

	def remove(self):
		"""
		Remove this XML node from the tree.
		"""
		self._element.getparent().remove(self._element)
		self._file.update()

	def xml(self, pretty_print: bool = True) -> str:
		"""
		Dump the given element to an XML string representation.

		:param pretty_print: Whether or not to pretty print the XML.

		:return: The XML string for this element.
		"""
		return etree.tostring(self._element, encoding="utf-8", pretty_print=pretty_print, xml_declaration=False, with_comments=True).decode("utf-8").strip()

	def __getitem__(self, tag):
		return self.find(tag)

	def __iter__(self):
		return iter(self.children)

	def __str__(self):
		return self.xml()

	def __repr__(self):
		return str(self.summary)


class _XmlAttributes:
	"""
	Proxy class for working with the attributes on an XML tag
	"""
	def __init__(self, parent: '_XmlElement'):
		self._parent = parent

	def _uri_to_prefix(self, value: str) -> str:
		for ns, uri in self._parent._element.nsmap.items():
			if ns is None:
				continue
			prefix = "{"+uri+"}"
			if value.startswith(prefix):
				base = value[len(prefix):]
				return f"{ns}:{base}"
		return value
	
	def _prefix_to_uri(self, value: str) -> str:
		for ns, uri in self._parent._element.nsmap.items():
			if ns is None:
				continue
			prefix = f"{ns}:"
			if value.startswith(prefix):
				base = value[len(prefix):]
				return "{" + uri + "}" + base
		return value

	@property
	def items(self) -> typing.Dict[str, str]:
		return { self._uri_to_prefix(key): value for key, value in self._parent._element.items() }

	def __getitem__(self, key):
		return self.items[key]

	def __setitem__(self, key, newvalue):
		self._parent._element.set(self._prefix_to_uri(key), newvalue)
		self._parent._file.update()

	def __delitem__(self, key):
		del self._parent._element.attrib[self._prefix_to_uri(key)]
		self._parent._file.update()

	def __str__(self):
		return str(self.items)

	def __repr__(self):
		return str(self)

