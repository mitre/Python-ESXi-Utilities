import typing

class NoOpLogger:
	def debug(self, msg): pass
	def info(self, msg): pass
	def warning(self, msg): pass
	def error(self, msg): pass
	def critical(self, msg): pass


Logger = NoOpLogger()
"""The logger instance to use for logging."""


def enable(handler: typing.Any):
	"""
	Enable logging using the given handler. This is duck-typed: the handler may be any object, as long as it implements the following function definitions::

		debug(str)
		info(str)
		warning(str)
		error(str)
		critical(str)

	:param handler: The handler to use.
	"""
	global Logger
	for method in [ "debug", "info", "warning", "error", "critical" ]:
		assert hasattr(handler, method) and callable(getattr(handler, method)), f"Handler does not implement method: {method}(str)"
	Logger = handler
	

def debug(msg: str):
	"""
	Write a debug message.

	:param msg: The message to write.
	"""
	global Logger
	Logger.debug(msg)


def info(msg: str):
	"""
	Write an info message.

	:param msg: The message to write.
	"""
	global Logger
	Logger.info(msg)


def warning(msg: str):
	"""
	Write a warning message.

	:param msg: The message to write.
	"""
	global Logger
	Logger.warning(msg)


def error(msg: str):
	"""
	Write an error message.

	:param msg: The message to write.
	"""
	global Logger
	Logger.error(msg)


def critical(msg: str):
	"""
	Write a critical message.

	:param msg: The message to write.
	"""
	global Logger
	Logger.critical(msg)
	