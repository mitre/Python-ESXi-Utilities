from esxi_utils.util import log, exceptions
import numpy as np
import cv2 as cv
import tempfile
import typing
import random
import time
import os


if typing.TYPE_CHECKING:
	from esxi_utils.vm.virtualmachine import VirtualMachine

class ScreenCaptureHandler:
	"""
	Handler class for capturing screens on a VirtualMachine (replaces VNC screen capture functions).

	:param vm:
		A `VirtualMachine` object
	"""
	def __init__(self, vm: 'VirtualMachine'):
		self._vm = vm
		self._client = vm._client

	def capture_screen(self, filename: str = '.', timeout: float = 30.0) -> str:
		"""
		Capture a screenshot of the VM's screen.
		Raises a 'VirtualMachineNotPoweredOnError' exception if the VM is powered off.
		Raises a 'ScreenshotError' exception if the screenshot task returns an error.

		:param filename: 
			Path to a file or directory where the screenshot should be captured.
			If a directory, the screenshot will be saved as `capture.png` in that directory.
		:param timeout:
			The maximum number of seconds to wait for the operation to complete before raising a `TimeoutError`.

		:return: The path to the saved screenshot.
		"""
		# request a screenshot of the VM be taken
		# CreateScreenshot() is also an option (not documented in API)
		screenshot_task = self._vm._vim_vm.CreateScreenshot_Task()
		# retries for MKS not available error
		retries = 0
		max_retries = 25
		# start time for generic timeout error
		start_time = time.time()
		while screenshot_task.info.state != 'success':
			s = screenshot_task.info.state
			if s == 'error':
				e = screenshot_task.info.error if screenshot_task.info.error else None
				str_e = ""
				if e:
					str_e = str(e).lower()
				screenshot_info_lower = str(screenshot_task.info).lower()
				if ( e and "mks' is not available" in str_e ) or "mks' is not available" in screenshot_info_lower or (e and "mksvmx' is not available" in str_e) or "mksvmx' is not available" in screenshot_info_lower:
					if retries >= max_retries:
						raise exceptions.ScreenshotError(self._vm, f'Failed to capture_screen (timeout)! ... task info: {screenshot_task.info}')
					log.debug(f"{str(self)} Mouse/Keyboard/Screen (MKS or MKSVMX) device not available for screenshot, retrying...")
					screenshot_task = self._vm._vim_vm.CreateScreenshot_Task()
					time.sleep(1)
					retries += 1
					continue
				elif self._vm.powered_off or ( e and "(powered off)." in str_e ) or "(powered off)." in screenshot_info_lower:
					raise exceptions.VirtualMachineNotPoweredOnError(self._vm)
				if e:
					log.error(f'Screenshot Task error returned by ESXi: {str(e)}')
				raise exceptions.ScreenshotError(self._vm, f'Failed to capture_screen (uncaught exception)! ... task info: {screenshot_task.info}')
			if s == 'queued':
				now = time.time()
				if now >= start_time + timeout:
					raise exceptions.ScreenshotError(self._vm, f'Failed to capture_screen! Timeout! Task info: {screenshot_task.info}')
			# else state is either 'running' or 'success'
		
		# result format:
		# '[datastore_name] VM_name/VM_name-3.png',
		result: str = screenshot_task.info.result

		# find the datastore name and the file path in the screenshot result
		second_bracket: int = result.find(']')
		ds_name: str = result[result.find('[')+1:second_bracket]
		remote_file_path: str = result[second_bracket+1:].strip()

		# Input validation for requested output path
		output_filepath = ScreenCaptureHandler._handle_file_pathing(filename)

		# find the datastore with the given name
		ds_obj = None
		for ds in self._vm._client.datastores:
			if ds.name == ds_name:
				ds_obj = ds
				break
		if ds_obj is None:
			raise exceptions.DatastoreNotFoundError(ds_name)
		
		# grab the DatastoreFile object that represents the created screenshot
		ds_image_file = ds_obj.root / remote_file_path
		# Download the screenshot from the datastore and save it to the requested filename
		dr = ds_image_file.download(dst=output_filepath, overwrite=True)
		# Remove the screenshot from the datastore
		ds_image_file.remove()
		# return the path to the created file
		return dr[0]

	@staticmethod
	def _handle_file_pathing(filename: str):
		"""
		Ensures that the filename provided by the user points to a valid path
		
		:param filename:
			the filename to verify/fix
		:return:
			the verified/corrected filename
		"""
		filename = os.path.abspath( os.path.expanduser(filename) )
		if os.path.isdir(filename):
			filename = os.path.join(filename, "capture.png")
		if not filename.lower().endswith(".png"):
			filename += ".png"
		if not os.path.isdir(os.path.dirname(filename)):
			raise NotADirectoryError(f"{os.path.dirname(filename)} is not an existing directory")
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

		:param dirname:
			The directory in which to save screenshots. Screenshots will be PNG files named with the time they are taken (nanoseconds since epoch).
		:param timeout:
			The maximum number of seconds to wait per screenshot.
		:param continue_on_timeout:
			Whether to continue taking screenshots if a timeout is reached (if ``False``, a ``TimeoutError`` is raised instead).
		:param pause:
			Number of seconds to pause between each screenshot.
		:param continuefunc:
			An optional function that is called prior to taking each screenshot. If this function returns ``False``, no more screenshots will be taken and this generator will exit.

		:yields:
			The paths to each screenshot taken.
		"""
		assert isinstance(dirname, str) and len(dirname) > 0, "dirname not specified"
		assert isinstance(timeout, (int, float)) and timeout > 0, "timeout is not a number greater than 0"
		assert isinstance(continue_on_timeout, bool), "continue_on_timeout is not boolean"
		assert isinstance(pause, (int, float)) and pause >= 0, "pause is not a number greater or equal to 0"
		assert continuefunc is None or callable(continuefunc), "continuefunc is not None or a callable"

		if not os.path.isdir(dirname):
			raise NotADirectoryError(f"{dirname} is not a directory")
		
		def vm_is_off():
			log.debug(f"{str(self)} Cannot take screenshot: VM is powered off. Waiting for power on...")
			time.sleep(10)

		while continuefunc is None or continuefunc() != False:
			if self._vm.powered_off:
				vm_is_off()
				continue
			try:
				path = os.path.join(dirname, str(time.time_ns()) + ".png")
				path = self.capture_screen(filename=path, timeout=timeout)
				yield path
			except TimeoutError as e:
				if not continue_on_timeout:
					raise e
			except exceptions.VirtualMachineNotPoweredOnError:
				vm_is_off()
				continue
			if pause:
				time.sleep(pause)

	def expect_screen(self, filename: str, timeout: int = 60, match_score: float = 0.99):
		"""
		Wait until the display matches a target image. If this fails to get a match on the display in time, a `TimeoutError` will be raised.

		If the provided image is a different size than the image obtained from the screen, scaling will be automatically applied to make the images comparible.

		:param filename: An image file to read and compare against.
		:param timeout: The maximum number of seconds to wait for the operation to complete before raising a `TimeoutError`.
		:param match_score: The minimum score in range [0.0, 1.0] for images to be considered a match (higher is a closer match). A value of 1.0 indicates an exact match.
		"""
		assert isinstance(filename, str) and len(filename) > 0, "filename not specified"

		filename = os.path.abspath(filename)
		if not os.path.isfile(filename):
			raise FileNotFoundError(f"{filename} is not a file")

		target_image = cv.imread(filename)
		if target_image is None:
			raise ValueError(f"File {filename} could not be read. Ensure that this file exists and is a valid image.")
		
		def compare(image: np.ndarray, template: np.ndarray) -> float:
			try:
				res = cv.matchTemplate(image, template, cv.TM_CCOEFF_NORMED)
				score = cv.minMaxLoc(res)[1]
				return score
			except Exception:
				return 0.0

		with tempfile.TemporaryDirectory() as tempdir:

			start_time = time.time()
			while True:
				if time.time() >= start_time + timeout:
					raise TimeoutError(f"{self}: timeout while attempts to match screen to {filename}")
				
				try:
					capture_path = self.capture_screen(os.path.join(tempdir, 'screenshot.png'))
					captured_image = cv.imread(capture_path)
					if captured_image is None:
						raise RuntimeError("imread failed")
					
					# Use OpenCV to compare the images
					if captured_image.shape == target_image.shape:
						if compare(captured_image, target_image) >= match_score:
							return
					else:
						# Compare scaled versions to handle different sizes
						scaled_target_image = cv.resize(target_image, (captured_image.shape[1], captured_image.shape[0]), interpolation=cv.INTER_LINEAR)
						if compare(captured_image, scaled_target_image) >= match_score:
							return
						
						scaled_captured_image = cv.resize(captured_image, (target_image.shape[1], target_image.shape[0]), interpolation=cv.INTER_LINEAR)
						if compare(scaled_captured_image, target_image) >= match_score:
							return
						
				except Exception as e:
					if not 'operation is not allowed in the current state' in str(e):
						raise e
				
				time.sleep(0.5 + random.random()) # Add some randomness to avoid cycles where alternating images (e.g. blinking cursor) synchronizes with the screenshots
			
	def __str__(self):
		return f"<{type(self).__name__} for {self._vm.name}>"
	
	def __repr__(self):
		return str(self)
