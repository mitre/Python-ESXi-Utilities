import functools
import typing
import random
import time

def retry_on_error(errors: typing.List[typing.Type[BaseException]], max_attempts: int = 10, pause_between_attempts: typing.Union[float, typing.Tuple[float, float]] = 0):
	"""
	Decorator to automatically re-attempt a function when the function encounters one of the given errors.
	
	:param errors: List of exceptions to re-attempt the function for. Matching is done using ``isinstance``.
	:param max_attempts: The maximum number of attempts before the function should truly error.
	:param pause_between_attempts: The time to pause between attempts. If a single number, this is the amount of seconds to pause. If a 2-tuple, this is the range of uniformly-selected random seconds to pause.
	"""
	def wrapper(f):
		@functools.wraps(f)
		def innerwrapper(*args, **kwargs):
			for i in range(max_attempts-1):
				try:
					return f(*args, **kwargs)
				except BaseException as e:
					if not any([ isinstance(e, errortype) for errortype in errors ]):
						raise e
				time.sleep(pause_between_attempts if isinstance(pause_between_attempts, (float, int)) else random.uniform(pause_between_attempts[0], pause_between_attempts[1]))
			return f(*args, **kwargs) # Last attempt
		return innerwrapper
	return wrapper