from esxi_utils.util import log, exceptions
from vncdotool import api as vncdotool_api
import random
import typing
import time
import os

if typing.TYPE_CHECKING:
	from esxi_utils.vm.virtualmachine import VirtualMachine

class VNCHandler:
	"""
	Handler class for using VNC on a VirtualMachine.

	:param vm: A `VirtualMachine` object
	"""
	def __init__(self, vm: 'VirtualMachine'):
		self._vm = vm
		self._client = vm._client

	def disable(self):
		"""
		Disables VNC.
		"""
		log.debug(f"{str(self)} Disabling...")
		self._vm.vmx = { key: value for key, value in self._vm.vmx.items() if not key.lower().startswith("remotedisplay.vnc.") }

	def enable(self, port: typing.Optional[int] = None) -> int:
		"""
		Enables VNC. Note that the ESXi server must be configured to allow ports 5900-6000 for VNC to work.

		:param port: The VNC port to use. If None, the VNC port will be auto-detected.

		:return: The VNC port assigned to this VM.
		"""
		if port is None:
			ports = self._client.firewall.find_vnc_port()
			if len(ports) == 0:
				raise exceptions.FirewallError(self, "Failed to determine a valid VNC port, check your connection and firewall rules to ensure incoming ports 5900-6000 are allowed")
			port = ports[random.randint(0, len(ports)-1)] # Choose a random VNC port from the list of valid ports
		log.debug(f"{str(self)} Enabling on port {port}...")
		vmx = self._vm.vmx
		vmx["remotedisplay.vnc.enabled"] = "TRUE"
		vmx["remotedisplay.vnc.port"] = str(port)
		self._vm.vmx = vmx
		return port

	def url(self) -> typing.Union[str, None]:
		"""
		Returns the VNC URL to this VM. VNC must be enabled on the VM.

		:return: A URL to use for connecting over VNC, or None if VNC is not enabled.
		"""
		vmx = self._vm.vmx
		if "remotedisplay.vnc.port" not in vmx:
			return None
		port = vmx["remotedisplay.vnc.port"]
		return f"{self._client.hostname}::{port}"

	def press_key(self, key: str, timeout: int = 30):
		"""
		Uses VNC to simulate a key press on the remote VM. Raises an exception is VNC is not enabled.

		The key is sent as if a user was writing over a UI. It is up to the user to ensure that the VM
		is in a state to properly receive the key press (i.e. the console is open if trying to write to
		a console).

		:param key: The key to send over VNC.
		:param timeout: The maximum number of seconds to wait for the operation to complete before raising a `TimeoutError`.
		"""
		log.debug(f"{str(self)} Simulating key press: {key}")
		vnc_url = self.url()
		if vnc_url is None:
			raise exceptions.VNCNotEnabledError(self._vm)
		with vncdotool_api.connect(vnc_url) as client:
			client.timeout = timeout
			client.keyPress(key)

	def write(self, text: str, enter: bool = False, timeout: int = 30):
		"""
		Uses VNC to simulate writing text on the remote VM. Raises an exception is VNC is not enabled.

		The keys are sent as if a user was writing over a UI. It is up to the user to ensure that the VM
		is in a state to properly receive the key presses (i.e. the console is open if trying to write to
		a console). 

		:param text: The text to write over VNC.
		:param enter: Boolean value whether to send the `ENTER` key after writing the text.
		:param timeout: The maximum number of seconds to wait for the operation to complete before raising a `TimeoutError`.
		"""
		log.debug(f"{str(self)} Simulating write: {text}")
		vnc_url = self.url()
		if vnc_url is None:
			raise exceptions.VNCNotEnabledError(self._vm)
		with vncdotool_api.connect(vnc_url) as client:
			client.timeout = timeout
			for char in text:
				if char.isupper() or char in r"~!@#$%^&*()_+{}|:\"<>?":
					# Requires shift key to be pressed
					client.keyDown('shift')
					client.keyPress(char)
					client.keyUp('shift')
				else:
					client.keyPress(char)
			if enter:
				client.keyPress('enter')
	
	def capture_screen(self, filename: str, timeout: float = 30.0):
		"""
		Capture a screenshot of the VM's screen.

		:param filename: 
			Path to a file or directory where the screenshot should be captured.
			If a directory, the screenshot will be saved as `capture.png` in that directory.
		:param timeout: 
			The maximum number of seconds to wait for the operation to complete before raising a `TimeoutError`.

		:return: The path to the saved screenshot.
		"""
		assert isinstance(filename, str) and len(filename) > 0, "filename not specified"
		vnc_url = self.url()
		if vnc_url is None:
			raise exceptions.VNCNotEnabledError(self._vm)
		filename = os.path.abspath(filename)
		if os.path.isdir(filename):
			filename = os.path.join(filename, "capture.png")
		if not filename.lower().endswith(".png"):
			filename += ".png"
		if not os.path.isdir(os.path.dirname(filename)):
			raise NotADirectoryError(f"{os.path.dirname(filename)} is not an existing directory")
		with vncdotool_api.connect(vnc_url) as client:
			client.timeout = timeout
			client.refreshScreen()
			client.captureScreen(filename)
		return filename

	def stream_screen(self, dirname: str, timeout: float = 5, continue_on_timeout: bool = True, pause: float = 0.0, continuefunc: typing.Optional[typing.Callable[[], bool]] = None) -> typing.Generator[str, None, None]:
		"""
		Continuously capture screenshots of the VM's screen in a loop. Use a ``break`` statement, ``.close()``, or the ``continuefunc`` parameter to exit the stream.

		Example usage (loop)::

			i = 0
			for screenshot_png in vm.vnc.stream_screen("screenshots/"):
				# screenshot_png = path to the taken screenshot
				# Do something with the screenshot
				i += 1
				if i == 10:
					break
					
		Example usage (next)::

			screenshot_generator = vm.vnc.stream_screen("screenshots/")
			screenshot_1_png = next(screenshot_generator)
			screenshot_2_png = next(screenshot_generator)
			screenshot_3_png = next(screenshot_generator)
			screenshot_generator.close()

		Example usage (callback)::

			i = 0
			for screenshot_png in vm.vnc.stream_screen("screenshots/", continuefunc=lambda: i < 10):
				# screenshot_png = path to the taken screenshot
				# Do something with the screenshot
				i += 1

		:param dirname: The directory in which to save screenshots. Screenshots will be PNG files named with the time they are taken (nanoseconds since epoch).
		:param timeout: The maximum number of seconds to wait per screenshot.
		:param continue_on_timeout: Whether to continue taking screenshots if a timeout is reached (if ``False``, a ``TimeoutError`` is raised instead).
		:param pause: Number of seconds to pause between each screenshot.
		:param continuefunc: An optional function that is called prior to taking each screenshot. If this function returns ``False``, no more screenshots will be taken and this generator will exit.

		:yields: The paths to each screenshot taken.
		"""
		assert isinstance(dirname, str) and len(dirname) > 0, "dirname not specified"
		assert isinstance(timeout, (int, float)) and timeout > 0, "timeout is not a number greater than 0"
		assert isinstance(continue_on_timeout, bool), "continue_on_timeout is not boolean"
		assert isinstance(pause, (int, float)) and pause >= 0, "pause is not a number greater or equal to 0"
		assert continuefunc is None or callable(continuefunc), "continuefunc is not None or a callable"

		vnc_url = self.url()
		if vnc_url is None:
			raise exceptions.VNCNotEnabledError(self._vm)
		
		if not os.path.isdir(dirname):
			raise NotADirectoryError(f"{dirname} is not a directory")
		
		client = vncdotool_api.connect(vnc_url)
		try:
			client.timeout = timeout
			while continuefunc is None or continuefunc() != False:
				try:
					path = os.path.join(dirname, str(time.time_ns()) + ".png")
					client.refreshScreen()
					client.captureScreen(path)
					yield path
				except TimeoutError as e:
					if not continue_on_timeout:
						raise e
				if pause:
					time.sleep(pause)
		finally:
			client.disconnect()

	def expect_screen(self, filename: str, maxrms: int = 0, timeout: int = 30):
		"""
		Wait until the display matches a target image. If this fails to get a match on the display in time, a `TimeoutError` will be raised.

		:param filename: An image file to read and compare against.
		:param maxrms: The maximum root mean square between histograms of the screen and target image.
		:param timeout: The maximum number of seconds to wait for the operation to complete before raising a `TimeoutError`.
		"""
		assert isinstance(filename, str) and len(filename) > 0, "filename not specified"
		vnc_url = self.url()
		if vnc_url is None:
			raise exceptions.VNCNotEnabledError(self._vm)
		filename = os.path.abspath(filename)
		if not os.path.isfile(filename):
			raise FileNotFoundError(f"{filename} is not a file")
		if not filename.lower().endswith(".png"):
			raise ValueError(f"{filename} is not a png file")
		with vncdotool_api.connect(vnc_url) as client:
			client.timeout = timeout
			client.refreshScreen()
			client.expectScreen(filename, maxrms=maxrms)
			
	def __str__(self):
		return f"<{type(self).__name__} for {self._vm.name}>"
	
	def __repr__(self):
		return str(self)
	
	def get_mks_ticket(self, webmks: bool = True):
		"""
		Ask the referenced VM to provide an authentication ticket.
		The requesting user must have the 'VirtualMachine.Interact.ConsoleInteract' privilege.

		:param webmks:
			If True: requests a 'webmks' ticket
			If False: requests a 'mks' ticket
			Both options will return a 'vim.VirtualMachine.Ticket' (read below)
		
		Returns a 'vim.VirtualMachine.Ticket' object for the mks protocol.
		Possible fields in the return object appear to be:
		- dynamicType <unset>
		- dynamicProperty (object)
		- ticket (string)
		- cfgFile (string)
		- host <unset>
		- sslThumbprint (string)
		- url <unset>

		Where <unset> values were observed on a non-vCenter system.
		"""
		ticket_type = 'webmks'
		if not webmks:
			ticket_type = 'mks'
		return self._vm._vim_vm.AcquireTicket(ticket_type)
