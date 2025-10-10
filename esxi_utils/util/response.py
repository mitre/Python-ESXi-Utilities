from esxi_utils.util import log, exceptions
from abc import ABC, abstractmethod
from lxml import etree
import typing
import json

class Response:
	"""
	Encapsulates the response (result) of a command.

	:param cmd: The command that was executed.
	:param stdout: The stdout of the command.
	:param stderr: The stderr of the command.
	:param status: The return code (status) of the command.
	"""
	def __init__(self, cmd: str, stdout: typing.Union[str, bytes], stderr: typing.Union[str, bytes], status: int):
		self.cmd = cmd
		self.stdout = stdout.decode("utf-8", errors="surrogateescape").strip() if isinstance(stdout, bytes) else stdout.strip()
		self.stderr = stderr.decode("utf-8", errors="surrogateescape").strip() if isinstance(stderr, bytes) else stderr.strip()
		self.status = status
		self.ok = status == 0
		log.debug(f"New Response Object: {str(self)}")

	def xml(self) -> 'etree._Element':
		"""
		Try to parse this response's `stdout` as XML.

		:return: An `etree._Element` for the root node. Raises an exception if the `stdout` cannot be parsed as XML.
		"""
		try:
			return etree.fromstring(self.stdout)
		except ValueError:
			return etree.fromstring(str.encode(self.stdout))

	def __str__(self):
		return json.dumps(self.__dict__, indent = 4)

	def __repr__(self):
		return f"<{type(self).__name__} for \"{self.cmd}\" (status {self.status})>"


class ResponsePromise(ABC):
	"""
	Encapsulates a Promise for a Response (result of a command).
	"""
	def __init__(self):
		self._resolved = False
		self._canceled = False

	@abstractmethod
	def wait(self) -> Response:
		"""
		Block until the underlying operation provides a response.

		:return: A ``Response`` for the operation.
		"""
		if self._canceled:
			raise exceptions.PromiseCanceledException()
		if self._resolved:
			raise exceptions.PromiseResolvedException()
		self._resolved = True

	@abstractmethod
	def cancel(self):
		"""
		Cancel the underlying operation.
		"""
		if self._canceled:
			raise exceptions.PromiseCanceledException()
		self._canceled = True
