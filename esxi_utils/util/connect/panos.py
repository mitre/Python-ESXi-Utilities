from dateutil.parser import parse as parsetime
from esxi_utils.util.response import Response
from esxi_utils.util import log, exceptions
from panos.errors import PanDeviceXapiError
from panos import firewall
import datetime
import netmiko
import typing
import time
import re
import requests
from requests.auth import HTTPBasicAuth
import warnings
import urllib3
import urllib.parse


class PanosAPIConnection:
	"""
	Send commands to the VM via the Palo Alto API.

	:param ip: The IP of the target.
	:param username: The username to use when logging into the remote system.
	:param password: The password to use when logging into the remote system.
	"""
	def __init__(self, ip, username, password):
		self._ip = ip
		self._username = username
		self._password = password
		self._connection = None
		self._http_url_base = "https://" + str(ip) + "/api/"

	def __enter__(self) -> 'PanosAPIConnection':
		self.open()
		return self

	def __exit__(self, *args):
		self.close()

	def open(self):
		"""
		Open a new connection. If an connection is already open, it will be closed before opening a new one.
		"""
		if self._connection:
			self.close()
		err = None
		try:
			self._connection = firewall.Firewall(self._ip, api_username=self._username, api_password=self._password)
			return
		except Exception as e:
			err = e
		self.close()
		raise exceptions.RemoteConnectionError(self, err)

	def close(self):
		"""
		Terminate the network connection to the remote end, if open.

		If no connection is open, this method does nothing.
		"""
		if self._connection:
			self._connection = None

	def wait(self, retries: int = 60, delay: int = 2, keep_open=False) -> bool:
		"""
		Waits until this connection can be established, and then establishes the connection.

		:param retries: How many times to retry connecting before exiting. Authentication errors will terminate the wait early.
		:param delay: How long to pause between retries in seconds.
		:param keep_open: Whether or not the keep the connection open. If `True`, it is left to the user to close the connection.

		:return: Whether or not the connection could be established
		"""
		for i in range(retries):
			if i != 0:
				time.sleep(delay)
			try:
				self.open()
				if not keep_open:
					self.close()
				return True
			except Exception:
				continue
		return False

	def exec(self, cmd: str, assert_status: typing.Optional[int] = None) -> 'Response':
		"""
		Execute a command using the Palo Alto firewall API. Acceptable commands can be found use https://<firewall ip>/api under operations.

		:param cmd: The command to run.
		:param assert_status: Assert that the command exits with a certain status number. If `None`, no assertion is made and checking the status is left to the caller. (Note: only 0 and 1 are valid statuses)
		
		:return: A `Response` object
		"""
		if self._connection is None:
			raise exceptions.RemoteConnectionNotOpenError(self)
		
		log.info(f"{str(self)} Running command: {cmd}")
		status_code = 0
		try:
			output = self._connection.op(cmd, xml=True)
		except PanDeviceXapiError as e:
			status_code = 1
			output = str(e)
		result = Response(cmd=cmd, stdout=output, stderr="", status=status_code)
		if assert_status is not None and assert_status != result.status:
			raise exceptions.RemoteConnectionCommandError(self, result)
		return result

	def show_all_interfaces(self) -> typing.Dict[str, typing.List[typing.Dict[str, typing.Any]]]:
		"""
		Finds all interface information for firewall.
		
		:return:
			An object containing hardware and logical interfaces ('hardware_interfaces' and 'logical_interfaces'). 
			
			Hardware interfaces use the following format::

				name
				id
				speed
				duplex
				state
				mac_address
			
			Logical interfaces::

				name
				id
				vsys
				zone
				forwarding
				tag
				address
		"""
		xml = self.exec('show interface "all"', assert_status=0).xml()
		hardware_interfaces = []
		for entry in xml.findall("./result/hw/entry"):
			hardware_interfaces.append({
				"name": entry.findtext("name"),
				"id": entry.findtext("id"),
				"speed": entry.findtext("speed"),
				"duplex": entry.findtext("duplex"),
				"state": entry.findtext("state"),
				"mac_address": entry.findtext("mac"),
			})
		
		logical_interfaces = []
		for entry in xml.findall("./result/ifnet/entry"):
			logical_interfaces.append({
				"name": entry.findtext("name"),
				"id": entry.findtext("id"),
				"vsys": entry.findtext("vsys"),
				"zone": entry.findtext("zone"),
				"forwarding": entry.findtext("fwd"),
				"tag": entry.findtext("tag"),
				"address": entry.findtext("ip"),
			})

		return {'hardware_interfaces': hardware_interfaces, 'logical_interfaces': logical_interfaces}

	def get_license_info(self):
		"""
		Returns the licenses currently installed on this device as a list.
		:return:
		A list of namedtuple objects. The list will be empty if no licenses are installed.
		The namedtuple attributes (in order) are:

		- feature (str)

		- description (str)

		- serial (str)

		- issued (datetime.date/None)

		- expires (datetime.date/None)

		- expired (bool)

		- authcode (str/None)

		"""
		return self._connection.request_license_info()

	def show_routing_ospf(self) -> typing.Dict[str, typing.Any]:
		"""
		Finds the ospf routing status
		
		:return: A list of routes and flag info ('routes', 'flags'). Each route object contains:

		- 'age'

		- 'destination'

		- 'flags' (array of flag values)

		- 'interface'

		- 'metric'

		- 'nexthop'

		- 'route-table'

		- 'virtual-router'

		"""
		xml = self.exec('show routing route type "ospf"', assert_status=0).xml()
		routes = [ ]
		for entry in xml.findall("./result/entry"):
			value = { child.tag: child.text for child in entry.getchildren() }
			value['flags'] = value['flags'].split()
			routes.append(value)

		flags = {}
		for m in re.findall('[^\s,]+:[^\s,]+', xml.findtext("./result/flags")):
			field, value = m.split(':')
			flags[field] = value

		return {'routes': routes, 'flags': flags}

	def get_panorama_status(self) -> typing.List[typing.Dict[str, typing.Any]]:
		"""
		Finds the panorama status

		:return: A list of status info for panorama servers. Each object contains fields:

		- name

		- address

		- Connected (yes/no)

		- HA state

		"""
		def _has_indent(line):
			return len(line)>len(line.lstrip())
		xml = self.exec('show panorama-status', assert_status=0).xml()
		lines = [ line for line in xml.findtext("./result").splitlines() if line and not line.isspace() ]
		results = []
		for line in lines:
			field,value = [part.strip() for part in line.split(':')]
			if not _has_indent(line):
				results.append({'name':field,'address':value})
			else:
				results[-1][field] = value
		return results

	def get_panorama_syslog_settings(self) -> typing.List[typing.Dict[str, typing.Any]]:
		"""
		Get the config settings for Panorama's syslog.
		
		:return: A list of status info for panorama servers. Each object contains fields:

		- transport

		- port

		- format

		- server (ip)

		- facility

		- name

		- short_name

		"""
		root = self.exec('show config running xpath "panorama/log-settings/syslog"', assert_status=0).xml()
		servers = []
		for entry in root.findall("./result/syslog/entry"):
			server = entry.find('./server/entry')
			obj = {child.tag:child.text for child in server}
			obj['name'] = entry.attrib['name']
			obj['short_name'] = server.attrib['name']
			servers.append(obj)
		return servers

	def get_netflow_server_profiles(self) -> typing.List[typing.Dict[str, typing.Any]]:
		"""
		Finds the netflow profile settings

		:return: A list of status info for netflow servers. Each object contains fields:

		- host (ip)

		- port

		- name

		"""
		root = self.exec('show config running xpath "shared/server-profile/netflow"', assert_status=0).xml()
		servers = []
		for profile in root.findall("./result/netflow/entry"):
			for server in profile.findall("./server/entry"):
				obj = {child.tag:child.text for child in server}
				obj['name'] = server.attrib['name']
				obj['profile_name'] = profile.attrib['name']
				servers.append(obj)
		return servers

	def time(self):
		"""
		Get the current time set on the remote host.

		:return: A `datetime` object.
		"""
		xml = self.exec('show clock', assert_status=0).xml()
		return parsetime(xml.findtext("./result").strip()).astimezone(datetime.timezone.utc)

	def shutdown(self):
		"""
		Perform a graceful shutdown of the VM using `request shutdown system`. This will close the current connection.
		"""
		result = self.exec("request shutdown system")
		if "command succeeded" not in result.stdout.lower():
			raise exceptions.RemoteConnectionCommandError(self, result)
		self.close()

	def __str__(self):
		return f"<{type(self).__name__} {self._username}@{self._ip}>"

	def __repr__(self):
		return str(self)

	def insecure_post_request(self, url: str, file=None):
		"""
		Use the 'requests' module to send a post request. Verify SSL will be set to 'False' and the insecure request warning will be suppressed.
		Will authenticate using 'HTTPBasicAuth' using the credentials given to this object on init.

		:param url: the URL to post to (including the query)
		:param file: (optional) a binary file to post to the URL

		:return: A requests `Response` object
		"""
		with warnings.catch_warnings():
			warnings.simplefilter('ignore', urllib3.exceptions.InsecureRequestWarning)
			if file:
				r = requests.post(url, auth=HTTPBasicAuth(self._username, self._password), files= {'file': file}, verify=False)
			else:
				r = requests.post(url, auth=HTTPBasicAuth(self._username, self._password), verify=False)
		return r

	def import_software_file(self, path_to_software_file: str, import_category: str):
		"""
		Import a software file to the VM via HTTP. You will still have to install it separately afterward.

		:param path_to_software_file: The software file you want to import into the VM. Will be read in and transferred as binary.
		:param import_category: The category is what 'type' of software this is, frequent examples are:

		- for anti-virus use: "anti-virus",

		- for apps or content use: "content",

		- for primary sofware version use: "software"

		:return: A requests `Response` object
		"""
		url = self._http_url_base + "?type=import&category=" + import_category
		with open(path_to_software_file, 'rb') as file:
			r = self.insecure_post_request(url, file)
		return r

	def import_configuration_file(self, path_to_file: str):
		"""
		Import a configuration file to the VM via HTTP. You will still have to install it separately afterward.

		:param path_to_file: The configuration file you want to import into the VM. Will be read in and transferred as binary.
		
		:return: A requests `Response` object
		"""
		url = self._http_url_base + "?type=import&category=configuration"
		with open(path_to_file, 'rb') as file:
			r = self.insecure_post_request(url, file)
		return r

	def install_license_file(self, path_to_license_file: str):
		"""
		Install a license file on the VM via HTTP.

		:param path_to_license_file: The license file you want to install. Will be sent as URL encoded plaintext to the VM via HTTP.

		:return: A requests `Response` object
		"""
		# this method is done via HTTP manually (instead of the op command) because the op command disfigures the key and fails.
		LICENSE_API_STRING_1 = '?type=op&cmd=%3Crequest%3E%3Clicense%3E%3Cinstall%3E'
		LICENSE_API_STRING_2 = '%3C%2Finstall%3E%3C%2Flicense%3E%3C%2Frequest%3E'
		with open(path_to_license_file, "r") as file:
			license_keycode = urllib.parse.quote( file.read().replace('\n', '\r\n').rstrip('\r\n').encode('utf-8'), safe='' )
		url = self._http_url_base + LICENSE_API_STRING_1 + license_keycode + LICENSE_API_STRING_2
		return self.insecure_post_request(url)

	# This API currently isn't working for me on 8.1.0 nor 10.1.8
	# I could just be making the request wrong, but the example their API builds in the browser also doesn't work.
	# def set_timezone(self, zone='UTC'):
	# 	"""
	# 	Change the timezone of the VM. See the Palo Alto docs for a list of all timezones.
	# 	:param zone: The requested timezone. Default is 'UTC'.

	# 	:return: A requests `Response` object
	# 	"""
	# 	timezone_string = f'?type=config&action=get&xpath=%2Fconfig%2Fdevices%2Fentry%5B%40name%3D%27localhost.localdomain%27%5D%2Fdeviceconfig%2Fsystem%2Ftimezone%2Fmember%5B%40name%3D%27{zone}%27%5D'
	# 	url = self._http_url_base + timezone_string
	# 	return requests.post(
	# 		url,
	# 		auth=HTTPBasicAuth(self._username, self._password),
	# 		verify=False
	# 	)

	def assign_serial_number(self, serial_no):
		"""
		Give the VM a serial number. This is only tested on Panorama devices and not recommended for use on firewalls.
		
		:param serial_no: The serial number to assign to this Panorama VM.

		:return: A requests `Response` object
		"""
		serial_str = f'?type=config&action=get&xpath=%2Fconfig%2Fmgt-config%2Fdevices%2F{serial_no}'
		url = self._http_url_base + serial_str
		return self.insecure_post_request(url)


class PanosSSHConnection:
	"""
	A SSH connection to a Palo Alto remote host.

	:param ip: The IP of the target.
	:param username: The username to use when logging into the remote system.
	:param password: The password to use when logging into the remote system.
	:param port: The port to use when connecting over SSH.
	"""
	def __init__(self, ip: str, username: str, password: str, port: int = 22):
		self._ip = ip
		self._username = username
		self._password = password
		self._port = port
		self._connection = None

	def __enter__(self) -> 'PanosSSHConnection':
		self.open()
		return self

	def __exit__(self, *args):
		self.close()

	def open(self):
		"""
		Open a new connection. If an connection is already open, it will be closed before opening a new one.
		"""
		if self._connection:
			self.close()
		self._connection = netmiko.ConnectHandler(device_type="paloalto_panos", host=self._ip, username=self._username, password=self._password, port=self._port).__enter__()

	def close(self):
		"""
		Terminate the network connection to the remote end, if open.

		If no connection is open, this method does nothing.
		"""
		if self._connection:
			self._connection.__exit__(None, None, None)
			self._connection = None

	def wait(self, retries: int = 60, delay: int = 2, keep_open=False) -> bool:
		"""
		Waits until this connection can be established, and then establishes the connection.

		:param retries: How many times to retry connecting before exiting. Authentication errors will terminate the wait early.
		:param delay: How long to pause between retries in seconds.
		:param keep_open: Whether or not the keep the connection open. If `True`, it is left to the user to close the connection.

		:return: Whether or not the connection could be established
		"""
		for i in range(retries):
			if i != 0:
				time.sleep(delay)
			try:
				self.open()
				if not keep_open:
					self.close()
				return True
			except Exception:
				continue
		return False

	def exec(self, cmd: str, assert_status: typing.Optional[int] = None) -> 'Response':
		"""
		Execute a command over SSH on this PanOS machine.

		:param cmd: The command to run.
		:param assert_status: Assert that the command exits with a certain status number. If `None`, no assertion is made and checking the status is left to the caller. (Note: only 0 and 1 are valid statuses)
		
		:return: A `types.Response` object
		"""
		if self._connection is None:
			raise exceptions.RemoteConnectionNotOpenError(self)
		
		log.info(f"{str(self)} Running command: {cmd}")
		error_regexes = ["^Server error", "^Invalid syntax", "^Unknown command"] # Since we cannot get the status code from the command, we'll try to detect errors by checking for known error strings
		output = self._connection.send_command(cmd)
		status_code = 0
		if len([r for r in error_regexes if re.search(r, output, flags=re.MULTILINE | re.IGNORECASE) is not None]) != 0:
			status_code = 1
		result = Response(cmd=cmd, stdout=output, stderr="", status=status_code)
		if assert_status is not None and assert_status != result.status:
			raise exceptions.RemoteConnectionCommandError(self, result)		
		return result

	def shutdown(self):
		"""
		Perform a graceful shutdown of the VM using `request shutdown system`. This will close the current connection.
		"""
		self.exec("request shutdown system", assert_status=0)
		self.close()

	def __str__(self):
		return f"<{type(self).__name__} {self._username}@{self._ip}>"

	def __repr__(self):
		return str(self)
