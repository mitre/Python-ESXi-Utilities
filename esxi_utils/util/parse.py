from datetime import datetime
import typing
import re

def size_string(size: str, unit: str = "KB") -> int:
	"""
	Convert a size string (e.g. 10MB, 10GB, etc.) into a integer equivalent in `unit`.

	:param size: The size string.
	:param unit: The unit (KB, MB, or GB) that the size string should be converted to.

	:return: The size converted to an int in `unit` units.
	"""
	CONVERSION_FACTORS = {
		"KB": 1,
		"MB": 1024,
		"GB": 1024 * 1024
	}
	assert unit in CONVERSION_FACTORS, f"Not a valid unit, use one of: {', '.join(list(CONVERSION_FACTORS.keys()))}"
	size = size.upper()
	from_unit = None
	for u in list(CONVERSION_FACTORS.keys()):
		if size.endswith(u):
			from_unit = u
			break
	if from_unit is None:
		raise ValueError(f"Not a valid unit for 'size'. Use one of: {', '.join(list(CONVERSION_FACTORS.keys()))}")

	size = size[:-len(from_unit)]
	try:
		size = int(size)
		if size < 1:
			raise ValueError("size cannot be less than 1")
	except ValueError:
		raise ValueError("size could not be read as a positive integer")
		
	size = size * CONVERSION_FACTORS[from_unit] # Convert to KB first
	size = size / CONVERSION_FACTORS[unit] # Convert to target unit
	return int(size)


def vimobj(vimobj_string: str, include_dtype: bool = True) -> typing.Dict[str, typing.Any]:
	"""
	Parse a vim object string into a dictionary.

	:param vimobj_string: The string.
	:param include_dtype: Include object types alongside their data.

	:return: A dictionary representation of the vim object.
	"""
	def vimcmd_lexer(src):
		tokens = []
		chars = ""
		for i, char in enumerate(src): 
			chars += char
			if chars.endswith("\n") or chars.endswith(","):
				value = chars[:-1].strip()
				if value == "true":
					tokens.append({ "type": "literal", "contents": True })
					chars = ""
				if value == "false":
					tokens.append({ "type": "literal", "contents": False })
					chars = ""
				if value == "null" or value == "<unset>":
					tokens.append({ "type": "literal", "contents": None })
					chars = ""
				try:
					x = int(value)
					tokens.append({ "type": "literal", "contents": x })
					chars = ""
				except ValueError:
					pass

				if (value.startswith("\"") or value.startswith("\'")) and len(value) > 1 and value.endswith(value[0]):
					# Try to parse the string ending here
					# Use a backtracking algorithm to continue the string if it cannot parse the remaining after this point
					try:
						x = vimcmd_lexer(src[i+1:])
						value = value[1:-1]
						try:
							# Try to parse as date
							value = datetime.fromisoformat(value.rstrip("Z"))
						except ValueError:
							pass
						tokens.append({ "type": "literal", "contents": value })
						tokens.extend(x)
						return tokens
					except Exception as e:
						pass

				elif len(tokens) != 0 and tokens[-1]["type"] == "field":
					# Catch-all
					# Also use a backtracking algorithm to continue if it cannot parse the remaining after this point
					try:
						x = vimcmd_lexer(src[i+1:])
						tokens.append({ "type": "literal", "contents": str(value) })
						tokens.extend(x)
						return tokens
					except Exception as e:
						pass

			stripped = chars.strip()
			if stripped == ",":
				chars = ""
				continue
			if re.match(r"\([^\)]+\)", stripped):
				tokens.append({ "type": "obj_name", "contents": stripped[1:-1] })
				chars = ""
			if stripped == "{":
				tokens.append({ "type": "open_bracket", "contents": dict() })
				chars = ""
			if stripped == "}":
				tokens.append({ "type": "close_bracket", "contents": None })
				chars = ""
			if stripped == "[":
				tokens.append({ "type": "open_list", "contents": list() })
				chars = ""
			if stripped == "]":
				tokens.append({ "type": "close_list", "contents": None })
				chars = ""
			if re.match(r"\S+ =", stripped):
				tokens.append({ "type": "field", "contents": stripped.split("=")[0].strip() })
				chars = ""
		
		if len(chars.strip()) != 0:
			raise ValueError(f"Failed to lex vim-cmd string: {src}\nRemaining chars: {chars}\nTokens: {tokens}")
		return tokens

	def vimcmd_parse_next(tokens):
		if tokens[0]["type"] == "literal":
			return (tokens[0]["contents"], tokens[1:])

		if tokens[0]["type"] == "obj_name":
			if tokens[1]["type"] == "literal":
				if include_dtype:
					return ({ "dtype": tokens[0]["contents"], "value": tokens[1]["contents"] }, tokens[2:])
				else:
					return (tokens[1]["contents"], tokens[2:])
			elif tokens[1]["type"] in ["open_bracket", "open_list"]:
				start_token = tokens[1]["type"]
				obj = tokens[1]["contents"]
				end_token = "close_bracket" if start_token == "open_bracket" else "close_list"
				num_open = 1
				inner_tokens = [ ]
				i = 2
				while num_open != 0:
					if tokens[i]["type"] == start_token:
						num_open += 1
					elif tokens[i]["type"] == end_token:
						num_open -= 1
					if num_open != 0:
						inner_tokens.append(tokens[i])
					i += 1

				while len(inner_tokens) != 0:
					if inner_tokens[0]["type"] == "field":
						field_name = inner_tokens[0]["contents"]
						obj[field_name], inner_tokens = vimcmd_parse_next(inner_tokens[1:])
					else:
						val, inner_tokens = vimcmd_parse_next(inner_tokens)
						obj.append(val)

				if include_dtype:
					return ({ "dtype": tokens[0]["contents"], "value": obj }, tokens[i:])
				else:
					return (obj, tokens[i:])
			else:
				raise ValueError(f"Unknown token for object: {str(tokens[1])}")
		raise ValueError(f"Unknown token: {str(tokens[1])}")

	def vimcmd_parse(src):
		src = src.replace("\r", "")
		match = re.search(r"^\([^\)]+\)\s+[\[|\{]", src, flags=re.MULTILINE)
		if match is None:
			raise ValueError("String is unparsable.")
		src = src[match.start():]
		tokens = vimcmd_lexer(src)
		return vimcmd_parse_next(tokens)[0]

	try:
		return vimcmd_parse(vimobj_string)
	except Exception as e:
		raise ValueError(f"Error while parsing vim object: {str(e)}")