from esxi_utils.util.connect.unix import UnixSSHConnection
from esxi_utils.util.parse import vimobj
from lxml import etree
import typing
import re


class ESXiSSHConnection(UnixSSHConnection):
	"""
	A SSH connection to a ESXi remote host.

	:param ip: The IP of the target.
	:param username: The username to use when logging into the remote system.
	:param password: The password to use when logging into the remote system.
	:param sudo_password: The password to use when running as sudo. Only necessary if the sudo password differs from `password`, as `password` will be used as the default.
	:param port: The port to use when connecting over SSH.
	"""

	def vimcmd(self, cmd: str, parse: bool = False, include_dtype: bool = True) -> typing.Union[str, typing.Dict[str, typing.Any]]:
		"""
		Executes a `vim-cmd` command on the ESXi server.

		:param cmd: Command to execute for `vim-cmd`
		:param parse: Attempt to parse the output as structured data. Only some commands can be parsed in this way; it is up to the caller to ensure that the command provided is one that returns a parsable format when this is `True`.
		:param include_dtype: Include object types when parse=`True`. For objects with a known and predictable structure, setting this to `False` may improve the usability/readability of the result.

		:return: A string of the command output if parse=`False`. If parse=`True`, a dict will be returned containing the parsed data.
		"""
		assert isinstance(cmd, str)
		cmd = re.sub("^vim-cmd", "", cmd.strip(), 1).strip()
		vimcmd_output = self.exec(f"vim-cmd {cmd}", assert_status=0).stdout
		return vimobj(vimcmd_output, include_dtype=include_dtype) if parse else vimcmd_output


	def esxcli(self, cmd: str, raw: bool = False)-> typing.Union[str, typing.Dict[str, typing.Any], typing.List[typing.Any]]:
		"""
		Executes a `esxcli` command on the remote server. Note: `esxcli` typically gives information about running VMs only.

		:param cmd: Command to execute for `esxcli`.
		:param raw: If True, return the raw (unparsed) output of the command as a string. Otherwise, automatically parse the output.

		:return: A string if `raw=True`, otherwise depends on the command output (common outputs are list or dict).
		"""
		assert isinstance(cmd, str)
		cmd = re.sub(r"^esxcli(\s*--formatter=\S*)?", "", cmd.strip(), 1).strip()
		cmd = f"esxcli {cmd}" if raw else f"esxcli --formatter=xml {cmd}"
		output = self.exec(cmd, assert_status=0).stdout
		if raw:
			return output

		def parse_xml_data(node):
			if node.tag == "list":
				data = list()
				for elem in node.findall("*"):
					data.append(parse_xml_data(elem))
				return data

			if node.tag == "structure":
				data = dict()
				for elem in node.findall("field"):
					field_name = elem.get("name")
					data[field_name] = parse_xml_data(elem)
				return data

			if node.tag == "field":
				field_value = node.find("*[1]")
				return parse_xml_data(field_value)

			if node.tag == "integer":
				return int(node.text)

			text = node.text
			if text is None:
				return ''
			return str(text)

		tree = etree.fromstring(output.encode())

		# Remove namespaces to make the tree easier to parse
		for elem in tree.getiterator(): 
			if not isinstance(elem, etree._Comment) and not isinstance(elem, etree._ProcessingInstruction):
				elem.tag = etree.QName(elem).localname

		# Parse
		root = tree.find(".//root")
		return parse_xml_data(root.find("*[1]"))