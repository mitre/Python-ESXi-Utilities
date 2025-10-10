from esxi_utils.vm.tools.guesttools import GuestTools
from esxi_utils.util.response import Response
from esxi_utils.util import exceptions
from esxi_utils.util import log
import pyVmomi
import time
import typing


class PanosGuestTools(GuestTools):
	"""
	Guest tools subclass specifically for interaction with Palo Alto systems.

	Wrapper class for functionality related to VMware Tools on a Virtual Machine. The virtual machine must have VMware tools installed for
	any of the contained functions to work.

	:param vm: A `VirtualMachine` object to wrap. VMware tools must be installed on this virtual machine.
	"""
	def execute_panos_cmd(
		self,
		username: str,
		password: str,
		cmd_list: list,
		list_delimiter: str = '%s\n',
		output_pipe_cmd: str = '',
		bash_path: str = "/bin/bash",
		timeout: typing.Optional[int] = 180,
		retry_timeout_minutes: int = 10
	) -> 'Response':
		"""
		Emulates sending commands on the Palo Alto CLI by piping a list of command strings into the Palo Alto CLI binary.
		Bash will be used as the underlying shell for interaction with the Palo Alto CLI binary.
		Systems without bash will fail. Sudo is not supported on Palo Alto machines.

		:param username:
			The username of the virtual machine user.
		:param password:
			The password of the virtual machine user.
		:param cmd_list:
			A list of 'Palo Alto CLI' commands to execute. This function will raise an exception if an empty list is given.
		:param list_delimiter:
			How to separate commands in the list. Default is 'newline' separation, which simulates pressing enter on the CLI itself.
		:param output_pipe_cmd:
			An optional command (or series of commands) to pipe the output of the CLI into. THESE ARE BASH COMMANDS. This will not be delimited.
		:param bash_path:
			The path to the bash executable.
		:param timeout:
			The command timeout in seconds. Set to 0 or `None` to disable timeout.
		:param retry_timeout_minutes:
			Certain exceptions can cause a 'retry' of the command:
			This value represents how many minutes to keep 'retrying' for.
		:return:
			A `types.Response` object
		"""
		self._assert_available()
		# Throw an error if the list is empty (the user likely expects a response of some kind, error prone to return anything)
		if len(cmd_list) <= 0:
			raise exceptions.GuestToolsError(self._vm, "ERROR: 'execute_panos_cmd' was given an empty list of commands to execute!")
		# Use printf with a given parameter delimiter/separator (typically newline) to pipe commands into the CLI binary
		cmd = f'printf \'{list_delimiter}\''
		if not isinstance(cmd_list, list):
			cmd_list = [cmd_list]
		# Build the command
		for entry in cmd_list:
			cmd += " '" + entry + "' "
		# Build the pipe into the binary
		cmd += "| /usr/local/bin/cli"
		# Pipe out into any additional commands
		if output_pipe_cmd != '':
			cmd += ' | ' + output_pipe_cmd

		timeout_time = retry_timeout_minutes * 60
		start_time = time.time()
		while True:
			try:
				with self.use_temporary_file(username=username, password=password, extension=".sh") as script_path:
					self.write_file(username=username, password=password, filepath=script_path, data=cmd)
					response = self.execute_program(
						username=username,
						password=password,
						command=f"{bash_path} {script_path}",
						timeout=timeout
					)
					return Response(cmd=cmd, stdout=response.stdout, stderr=response.stderr, status=response.status)
			except pyVmomi.vmodl.fault.SystemError as e:
				log.debug(f'\nWARN: Caught pyVmomi "vmodl.fault.SystemError" exception while trying to execute_panos_cmd! Will ignore and try again. Error: {str(e)} ... Retrying...')
			except pyVmomi.vim.fault.InvalidState as e2:
				log.debug(f'\nWARN: Caught pyVmomi "vim.fault.InvalidState" exception while trying to execute_panos_cmd! Will ignore and try again. Error: {str(e2)} ... Retrying...')
			if start_time + timeout_time <= time.time():
				raise Exception('ERROR: Timeout while trying to execute panos command! The "cmd" variable: ' + cmd)
			# end try/except
		# end while loop
	# end fn execute_panos_cmd

	def show_system_info(self, username: str, password: str) -> 'Response':
		"""
		Executes the command 'show system info' on the Palo Alto CLI.

		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.

		:return: A `types.Response` object
		"""
		return self.execute_panos_cmd(username, password, ['show system info'])

	def get_ip_address(self, username: str, password: str) -> 'Response':
		"""
		Executes the command 'show system info' on the Palo Alto CLI and then does a linux 'grep' for 'ip-address'

		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.

		:return: A `types.Response` object
		"""
		return self.execute_panos_cmd(username, password, ['show system info'], output_pipe_cmd='grep ip-address')

	def set_ip_address(
		self,
		username: str,
		password: str,
		ip_address: str,
		netmask: str,
		default_gateway: typing.Optional[str],
		type: str = 'static'
	) -> 'Response':
		"""
		Executes a series of Palo Alto CLI commands to change the IP address of the VM.
		- enters 'configure' mode
		- executes 'set deviceconfig system ip-address....' and provides the given values as arguments
		- commits changes

		:param username:
			The username of the virtual machine user.
		:param password:
			The password of the virtual machine user.
		:param ip_address:
			The IP address to assign to the VM.
		:param netmask:
			The netmask to apply to the VM.
		:param default_gateway:
			The default gateway to apply the VM (can be None).
		:param type:
			Known good value is 'static' (as in 'static IP'). Change at your own risk.
		:return:
			A `types.Response` object
		"""
		gateway_str = f' default-gateway {default_gateway}'
		if default_gateway is None:
			gateway_str = ''
		ip_config_cmd = f'set deviceconfig system ip-address {ip_address} netmask {netmask}{gateway_str} type {type}'
		return self.execute_panos_cmd(username, password, ['configure t', ip_config_cmd, 'commit force'])

	def set_password(self, username: str, old_password: str, new_password: str) -> 'Response':
		"""
		Executes a series of Palo Alto CLI commands to chage the password for the given username.
		- enters 'configure' mode
		- executes 'set mgt-config users admin password'
		- inputs the new_password (twice)
		- commits changes

		:param username: The username of the virtual machine user. This username's password will be changed.
		:param old_password: The password of the virtual machine user.
		:param new_password: The password to give to the provided username.

		:return: A `types.Response` object
		"""
		return self.execute_panos_cmd(username, old_password, ['configure t', f'set mgt-config users {username} password', new_password, new_password, 'commit force'])


	def create_new_user(
		self,
		existing_admin_username: str,
		existing_admin_password: str,
		new_username: str,
		new_password: str
	) -> 'Response':
		"""
		Executes a series of Palo Alto CLI commands to create a new user on the VM.
		- enters 'configure' mode
		- executes 'set mgt-config users <username> password'
		- inputs the new_password (twice)
		- commits changes

		:param existing_admin_username:
			The username of the virtual machine user admin that already exists.
		:param existing_admin_password:
			The password of the virtual machine user admin that already exists.
		:param new_username:
			The username of the virtual machine user to create.
		:param new_password:
			The password to give to the provided username.

		:return:
			A `types.Response` object for the executed command
		"""
		return self.execute_panos_cmd(existing_admin_username, existing_admin_password, ['configure t', f'set mgt-config users {new_username} password', new_password, new_password, 'commit force']) 


	def give_user_superuser_rights(
		self,
		existing_admin_username: str,
		existing_admin_password: str,
		username_to_give_rights_to: str,
		readonly: bool = False
	) -> 'Response':
		"""
		Executes a series of Palo Alto CLI commands to give superuser rights to the provided username.
		- enters 'configure' mode
		- executes 'set mgt-config users <username> permissions role-based super<user/reader> yes'
		- commits changes

		:param existing_admin_username:
			The username of the virtual machine user admin that already exists.
		:param existing_admin_password:
			The password of the virtual machine user admin that already exists.
		:param username_to_give_rights_to:
			The username of the virtual machine user to give rights to
		:param readonly:
			Assign the role 'superreader' instead of 'superuser'

		:return: A `types.Response` object for the executed command
		"""
		if readonly:
			role = 'superreader'
		else:
			role = 'superuser'
		return self.execute_panos_cmd(existing_admin_username, existing_admin_password, ['configure t', f'set mgt-config users {username_to_give_rights_to} permissions role-based {role} yes', 'commit force'])


	def enable_server_verification(self, username: str, password: str, enable: bool = True, timeout: int = 180) -> 'Response':
		"""
		Executes a series of Palo Alto CLI commands to enable server-verification.
		- enters 'configure' mode
		- executes 'set deviceconfig system server-verification yes'
		- commits changes

		:param username: The username of the virtual machine user.
		:param password: The password of the virtual machine user.
		:param enable: When set to True: enables server-verification. When False: disables server-verification (not recommended)
		:param timeout: How long in seconds to wait for retry.
		
		:return: A `types.Response` object
		"""
		cmd = 'set deviceconfig system server-verification '
		if enable:
			cmd += 'yes'
		else:
			cmd += 'no'
		return self.execute_panos_cmd(username, password, ['configure', cmd, 'commit force'], timeout=timeout)


	def load_configuration_file(self, non_default_username: str, password: str, filename: str) -> 'Response':
		"""
		Executes a series of Palo Alto CLI commands to load an XML configuration file.
		- enters 'configure' mode
		- executes 'load config from <filename>'
		- commits changes

		:param non_default_username:
			The username of a VM 'superuser' that isn't the default user (typically 'admin').
			This is important because the default username typically has the password overwritten.
		:param password:
			The password for the 'non_default_username'.
		:param filename:
			The name of the file (NOT the path) to load.

		:return: A `types.Response` object for the executed command
		"""
		return self.execute_panos_cmd(non_default_username, password, ['configure t', f'load config from {filename}', 'commit force'])
