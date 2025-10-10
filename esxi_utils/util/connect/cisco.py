from esxi_utils.util.connect.ssh import SSHConnection
from dateutil.parser import parse as parsetime
import pkg_resources
import datetime
import textfsm
import typing
import re

if typing.TYPE_CHECKING:
	from esxi_utils.util.response import Response

class CiscoSSHConnection(SSHConnection):
	"""
	A SSH connection to a Cisco remote host.

	:param ip: The IP of the target.
	:param username: The username to use when logging into the remote system.
	:param password: The password to use when logging into the remote system.
	:param port: The port to use when connecting over SSH.
	"""

	def exec(
		self, 
		cmd: str, 
		stdin: typing.Optional[typing.Dict[str, str]] = None, 
		timeout: int = 120, 
		out_stream_callback: typing.Optional[typing.Callable[[str], None]] = None, 
		remove_banner: bool = True,
		network_retries: int = 0,
	) -> 'Response':
		"""
		Execute a shell command on the remote end of this connection. Includes some Cisco-specific functionality, such as ignoring login headers.

		:param cmd: The command to run.
		:param stdin: A dict mapping a 'pattern' (regex string) to a 'response' (string), to input 'response' to stdin when stdout matches 'pattern'
		:param timeout: The command timeout in seconds. Set to 0 to disable timeout.
		:param out_stream_callback: Optional callback to handle the stdout of commands. If not `None`, this will be called as a command's stdout becomes available.
		:param remove_banner: Whether or not to auto-detect and remove login banners from the resulting output.
		:param network_retries: Number of times to retry the command when a recoverable network error is encountered. The command should be idempotent when this is non-zero as it may run several times.

		:return: A `Response` object.
		"""
		banner = None
		if remove_banner:
			banner_resp = SSHConnection.exec(self, cmd="show clock", network_retries=3).stdout.replace('\r', '').rstrip()
			banner_end = banner_resp.rfind("\n") # Find the last newline
			if banner_end != -1:
				# The banner is everything up to and including the last newline character, 
				# since the 'show clock' command predictably outputs a single line without any control characters
				banner = banner_resp[:banner_end+1]

		resp = SSHConnection.exec(self, cmd=cmd, stdin=stdin, timeout=timeout, pty=False, out_stream_callback=out_stream_callback, network_retries=network_retries)
		resp.stdout = resp.stdout.replace('\r', '')
		if banner:
			resp.stdout = resp.stdout[len(banner):]
		return resp

	def show_ip_interface_brief(self) -> typing.List[typing.Dict[str, typing.Any]]:
		"""
		Finds the ip interface information
		
		:return: A list of objects containing interface information with the following fields:

		- Interface

		- IP-Address

		- OK?

		- Method

		- Status
		
		- Protocol

		"""
		return self._parse_table(
			stringtable=self.exec("show ip interface brief", network_retries=3).stdout, 
			headers=['Interface', 'IP-Address', 'OK?', 'Method', 'Status', 'Protocol']
		)

	def show_ip_ospf_neighbor(self) -> typing.List[typing.Dict[str, typing.Any]]:
		"""
		Finds the ospf neighbors
		
		:return: A list of objects containing interface information with the following fields:

		- Address

		- Dead Time

		- Interface

		- Neighbor ID

		- Pri

		- State

		"""
		return self._parse_table(
			stringtable=self.exec("show ip ospf neighbor", network_retries=3).stdout, 
			headers=['Neighbor ID', 'Pri', 'State', 'Dead Time', 'Address', 'Interface']
		)

	def show_license_usage(self) -> typing.Dict[str, typing.Any]:
		"""
		Finds the license usage.
		
		:return: The license usage for the cisco machine.
		"""
		parsed_data = self._parse_set(
			set_string=self.exec("show license usage", network_retries=3).stdout, 
			first_line='License Authorization:'
		)
		return_obj = dict()
		return_obj['Licenses'] = [ value for field, value in parsed_data.items() if field != 'License Authorization']
		return return_obj

	def get_logging_trap_info(self) -> typing.List[typing.Dict[str, typing.Any]]:
		"""
		Returns the logging trap info from show logging
		
		:return: Logging trap info summary
		"""
		output = self.exec("show logging", network_retries=3).stdout
		template = pkg_resources.resource_filename(__name__, 'textfsm_templates/show_logging_trap_info.textfsm')
		with open(template) as f:
			re_table = textfsm.TextFSM(f)
			header = re_table.header
			results = re_table.ParseText(output)
			return [{ header[i]: r[i] for i in range(len(header)) } for r in results[:-1] ]

	def get_flow_exporter_info(self) -> typing.List[typing.Dict[str, typing.Any]]:
		"""
		Returns the flow exporter info

		:return: Flow exporter info summary
		"""
		output = self.exec("show run flow exporter", network_retries=3).stdout
		template = pkg_resources.resource_filename(__name__, 'textfsm_templates/show_run_flow_exporter.textfsm')
		with open(template) as f:
			re_table = textfsm.TextFSM(f)
			header = re_table.header
			results = re_table.ParseText(output)
			return [{ header[i]: r[i] for i in range(len(header)) } for r in results ]

	def time(self):
		"""
		Get the current time set on the remote host.

		:return: A datetime object
		"""
		date = self.exec("show clock", network_retries=3).stdout.splitlines()[-1].strip()
		if date.startswith('*'):
			date = date[1:]
		return parsetime(date).astimezone(datetime.timezone.utc)

	def _parse_table(self, stringtable, headers):
		"""
		Parses a table. This assumes data is contained within the headers, e.g.
		header1          header2
		value1           value2
		superlongvalue1  superlongvalue2

		object2:
		 subfield3:subvalue3

		:param stringtable: String that contains table to be parsed
		:param headers: List of headers in tables
		
		:return: A list of objects whose fields match the headers.
		"""
		# Remove empty lines and whitespace lines
		lines = list(filter(lambda str: str and not str.isspace(),stringtable.splitlines()))
		regex = re.compile('\s*'+'\s*'.join([re.escape(head) for head in headers])+'\s*')
		
		# Find the header of the table
		while lines and not regex.match(lines[0]):
			lines.pop(0)

		if len(lines)==0:
			raise ValueError(f"Table with headers {headers} not found in string {stringtable}")

		# Find where each header starts
		head_index = [lines[0].find(head) for head in headers]
		# Add the end of the line
		head_index.append(None)
		
		return [ { headers[idx]: line[head_index[idx]:head_index[idx+1]].strip() for idx in range(len(headers)) } for line in lines[1:] ]

	def _parse_set(self, set_string, indent=2, first_line=None):
		"""
		Parses a set, e.g. data in the form
		object1:
		  subfield1:subvalue1
		  subfield2:subvalue2
		  subobject1:
		    subsubfield1:subsubvalue1

		object2:
		  subfield3:subvalue3

		:set_string: String to parse
		:indent: Default 2. Number of characters per left indent.
		
		:return:
			The set converted to a dictionary. In the above example, the result would be::

				{
					object1:
					{
						subfield1:subvalue1,
						subfield2:subvalue2,
						subobject1:{
							subsubfield1:subsubvalue1
						}

					},
					object2:{
						subfield3:subvalue3
					}
				}
		"""
		lines = list(filter(lambda str: str and not str.isspace(),set_string.splitlines()))

		# Find where the set begins
		while lines and first_line and lines[0].strip()!=first_line:
			lines.pop(0)

		# Start with an empty object
		obj_stack = [{}]

		def _num_white_space(line):
			return len(line)-len(line.lstrip())

		for line in lines:
			split = line.split(':')

			if len(split)==1:
				raise ValueError(f'Each line of set_string must be of the form field:value or field:\n{set_string}')

			field = split[0].strip()
			value = split[1].strip()

			if _num_white_space(line)%indent !=0:
				raise ValueError(f'Error with line \n{line}\n. Each line must have a left indent of multiple {indent}. This line has an indent with {_num_white_space(line)} characters.')
			# The length of the stack (minus 1) matches the depth of the current
			# object. If the indent is less, pop the obj_stack until
			# you get the object that matches the current depth. 
			while _num_white_space(line) < (len(obj_stack)-1)*indent:
				obj_stack.pop()

			# If there is no value, that means we have a new object.
			if not value:
				obj_stack[-1][field] = {}
				obj_stack.append(obj_stack[-1][field])
			# Otherwise we add the current field/value to the current object
			else:
				obj_stack[-1][field] = value
		
		# Return the root object
		return obj_stack[0]