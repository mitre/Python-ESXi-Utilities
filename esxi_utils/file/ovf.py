from esxi_utils.file.xml import XmlFile
from esxi_utils.util import log, exceptions
from contextlib import contextmanager
import tempfile
import hashlib
import tarfile
import typing
import shutil
import os
import re

class OvfFile:
	"""
	OVF/OVA file for a pre-configured virtual machine image (virtual appliance), ready to run on a hypervisor. 
	This class provides utility functions for working with an OVF/OVA file, and is agnostic to the actual file format (note: OVA files may have some overhead and require additional disk usage for certain functionality).
	
	:param path: The path to the OVF/OVA file. This may also be a path to a directory containing the file, assuming only one such file exists in that directory (otherwise an exception is raised).
	"""
	def __init__(self, path: str):
		extensions = [".ovf", ".ova"]
		path = os.path.abspath(path)
		if os.path.isdir(path):
			# Is a directory
			# Detect files in this directory
			files = [ os.path.join(path, file) for file in os.listdir(path) if os.path.splitext(file)[1].lower() in extensions ]
			if len(files) == 0:
				raise exceptions.OvfFileNotFoundError(path, f"No OVF/OVA file found")
			if len(files) > 1:
				raise exceptions.OvfAmbiguityError(path, f"Multiple OVF/OVA files exist: {', '.join(files)}")
			path = files[0]
		
		if not os.path.isfile(path):
			raise exceptions.OvfFileNotFoundError(path, f"File does not exist")

		vapp_type = os.path.splitext(path)[1].lower()
		if vapp_type not in extensions:
			raise exceptions.OvfFileNotFoundError(path, f"Path does not point to a valid OVF/OVA file")

		self._path = path
		log.debug(f"{str(self)} Initialized")

	@property
	def path(self) -> str:
		"""
		The path associated with this file.

		:return: The absolute file path.
		"""
		if not os.path.exists(self._path):
			raise exceptions.OvfFileNotFoundError(self.path, f"File does not exist, it may have been moved or deleted")
		return self._path

	@property
	def ext(self) -> str:
		"""
		The extension associated with this file type.

		:return: This file type's extension (either '.ovf' or '.ova').
		"""
		return os.path.splitext(self.path)[1].lower()

	@property
	def is_archive(self) -> bool:
		"""
		Whether or not this is an archive type (i.e. '.ova')

		:return: A boolean
		"""
		return self.ext == ".ova"

	@property
	def descriptor_name(self) -> str:
		"""
		The name of the virtual appliance descriptor file (i.e. the OVF file itself).

		:return: The name of the descriptor file.
		"""
		if not self.is_archive:
			return os.path.basename(self.path)
		ovfs = [ file for file in self._list_files() if file.lower().endswith(".ovf") ]
		if len(ovfs) == 0:
			raise exceptions.OvfFileNotFoundError(self.path, f"Unable to find any OVF files")
		elif len(ovfs) > 1:
			raise exceptions.OvfAmbiguityError(self.path, f"Found several OVF files: {', '.join(ovfs)}")
		return ovfs[0]

	@property
	def manifest_name(self) -> typing.Union[str, None]:
		"""
		The name of the manifest file, if it exists.

		:return: The name of the manifest file, or `None` if it does not exist.
		"""
		descriptor_name = os.path.splitext(os.path.basename(self.descriptor_name))[0]
		for file in self._list_files():
			name, ext = os.path.splitext(file)
			if name == descriptor_name and ext.lower() == ".mf":
				return file
		return None

	@property
	def name(self) -> str:
		"""
		The name of the OVF/OVA.

		:return: A string
		"""
		return os.path.splitext(self.descriptor_name)[0]

	@property
	def vmname(self) -> str:
		"""
		The VM name specified in the OVF/OVA.

		:return: A string
		"""
		return self.descriptor.root["VirtualSystem"][0]["Name"][0].text

	@property
	def ostype(self) -> str:
		"""
		The VM OS type specified in the OVF/OVA.

		:return: A string
		"""
		return self.descriptor.root["VirtualSystem"][0]["OperatingSystemSection"][0].attributes["vmw:osType"]

	@property
	def networks(self) -> typing.List[str]:
		"""
		Get the networks assigned to the OVF/OVA.

		:return: A list of network names.
		"""
		network_sections = self.descriptor.root.find("NetworkSection")
		if len(network_sections) == 0:
			return []
		return [ network.attributes["ovf:name"] for network in network_sections[0]["Network"] ]

	@property
	def files(self) -> typing.List[str]:
		"""
		Get a list of all file names referenced by this virtual appliance (Note: does not check for file existence).

		:return: A list of all file names referenced by this virtual appliance.
		"""
		files = [self.descriptor_name]
		if self.manifest_name:
			files.append(self.manifest_name)
		files.extend([ file.attributes['ovf:href'] for file in self.descriptor.root["References"][0]["File"] ])
		return files

	@property
	def disks(self) -> typing.List[str]:
		"""
		Get a list of all disk names referenced by this virtual appliance (Note: does not check for file existence). This is a subset of `files`.

		:return: A list of all disk names referenced by this virtual appliance.
		"""
		root = self.descriptor.root
		file_id_to_name = { file.attributes['ovf:id']: file.attributes['ovf:href'] for file in root["References"][0]["File"] }
		disks = [ file_id_to_name[disk.attributes['ovf:fileRef']] for disk in root["DiskSection"][0]["Disk"] if disk.attributes['ovf:fileRef'] in file_id_to_name ]
		return disks

	def disk_sizes(self, unit: str = "KB") -> typing.Dict[str, int]:
		"""
		Get the sizes of disk for this virtual machine. 
		This is the maximum capacity of the disk when the OVF/OVA is deployed, not the size of the VMDK as stored on the filesystem.

		:param unit: The unit of measurement to use (one of: B, KB, MB, GB).

		:return: A dictionary mapping disk name to size
		"""
		conversion_factors = { "B": 1, "KB": 1024, "MB": 1024*1024, "GB": 1024*1024*1024 }
		assert unit in conversion_factors
		root = self.descriptor.root
		file_id_to_name = { file.attributes['ovf:id']: file.attributes['ovf:href'] for file in root["References"][0]["File"] }
		sizes = {}
		for disk in root["DiskSection"][0]["Disk"]:
			if disk.attributes['ovf:fileRef'] not in file_id_to_name:
				continue
			name = file_id_to_name[disk.attributes['ovf:fileRef']]
			units = disk.attributes["ovf:capacityAllocationUnits"]
			match = re.match(r"byte \* ([0-9]+)\^([0-9]+)", units)
			if not match:
				raise ValueError(f"Unrecognized capacityAllocationUnits for disk {disk.attributes['ovf:diskId']}: {units}")
			base = int(match.group(1))
			exp =  int(match.group(2))
			capacity = disk.attributes["ovf:capacity"]
			sizes[name] = (int(capacity) * pow(base, exp)) / conversion_factors[unit]
		return sizes

	def required_storage(self, unit: str = "KB") -> int:
		"""
		Get the amount of required storage to contain the VM represented by this virtual appliance. 
		This is the sum of all disk sizes, plus the size of any non-disk files.

		:param unit: The unit of measurement to use (one of: B, KB, MB, GB).

		:return: The storage space required by this OVF/OVA
		"""
		conversion_factors = { "B": 1, "KB": 1024, "MB": 1024*1024, "GB": 1024*1024*1024 }
		assert unit in conversion_factors
		root = self.descriptor.root
		disks = self.disk_sizes(unit="B")
		size = 0
		for file in root["References"][0]["File"]:
			name = file.attributes["ovf:href"]
			if name in disks:
				size += disks[name]
			else:
				size += int(file.attributes["ovf:size"])
		return size / conversion_factors[unit]

	@property
	def descriptor(self) -> 'XmlFile':
		"""
		Open the descriptor file for reading or writing. This returns a class that can be interacted with directly to read or write to the
		underlying descriptor file, and changes will automatically be applied.
		"""
		log.debug(f"{str(self)} Opening descriptor...")

		def update_func(new_xml):
			log.debug(f"{str(self)} Updating descriptor...")
			with self.open(self.descriptor_name, mode="w") as f:
				f.write(new_xml)

		with self.open(self.descriptor_name, mode="r") as f:
			return XmlFile(f, update_func)

	@contextmanager
	def open_descriptor(self) -> typing.Generator['XmlFile', None, None]:
		"""
		Open the descriptor file for reading or writing as a context manager.
		This behaves similarly to the `descriptor` property, but instead applies all changes to the underlying
		OVF at the end of the context for efficiency. This will perform faster when applying multiple changes
		to the descriptor than the `descriptor` property alone. 
		"""
		log.debug(f"{str(self)} Opening descriptor as context manager...")
		with self.open(self.descriptor_name, mode="r+") as f:
			d = XmlFile(f)
			yield d
			f.seek(0)
			f.truncate()
			f.write(d.xml(pretty_print=True, xml_declaration=True))

	@property
	def manifest(self) -> typing.Union[typing.Dict[str, typing.Tuple[str, str]], None]:
		"""
		The contents of the manifest file, as a dict.

		:return: A dict representation of the manifest file, or `None` if a manifest does not exist.
		"""
		if self.manifest_name is None:
			return None

		log.debug(f"{str(self)} Reading manifest...")

		manifest = {}
		with self.open(self.manifest_name, 'r') as f:
			for line in f.readlines():
				line = line.strip()
				if len(line) == 0:
					continue
				match = re.match(r"^(.*?)\((.*?)\)=\s*(.*)$", line)
				manifest[match.group(2)] = (match.group(1), match.group(3))
		return manifest

	@contextmanager
	def open(self, file: str, mode: str = "r") -> typing.Generator[typing.IO, None, None]:
		"""
		Open a file associated with this OVF/OVA.
		Note: For OVAs, this will incur additional overhead as the requested file must be extracted.

		:param file: The name of the file to open.
		:param mode: The mode in which to open the file. 
		"""
		log.info(f"{str(self)} Opening file {file} (mode={mode})")
		if not self.is_archive:
			file = file.strip(os.sep)
			path = os.path.join(os.path.dirname(self.path), file)
			with open(path, mode=mode) as f:
				yield f
			return
		
		# For an archive, we extract the file to a temporary directory and modify that file
		# If this file was modified (detected by hash changes), we'll then re-add that file back to the archive
		file = file.strip(os.sep)
		with tempfile.TemporaryDirectory(prefix="vapp") as tmpdir:
			with tarfile.open(self.path, "r") as tar:
				if file in tar.getnames():
					tar.extract(file, path=tmpdir)

			target = os.path.join(tmpdir, file)

			def get_hash():
				if not os.path.isfile(target):
					return None
				h = hashlib.sha1() # SHA-1 offers fast hashing speed
				with open(target, 'rb') as f:
					while True:
						data = f.read(65536)
						if not data:
							break
						h.update(data)
				return h.hexdigest()

			original_hash = get_hash()
			try:
				with open(target, mode=mode) as f:
					yield f
			finally:
				new_hash = get_hash() 
				log.debug(f"{str(self)} Closing file {file} (mode={mode}). Original hash = {original_hash}, new hash = {new_hash}")
				if new_hash != original_hash:
					log.debug(f"{str(self)} File {file} (mode={mode}) was updated, writing back...")
					# Hash changed, we need to update the original OVA
					# Since we can't update a tar in-place, we'll need to create a new tar archive
					# to replace the original
					with tempfile.TemporaryDirectory(prefix="vapp-tar") as tmptardir:
						new_tar_path = os.path.join(tmptardir, "vapp.tar")
						with tarfile.open(self.path, "r") as original_tar, tarfile.open(new_tar_path, "w", format=tarfile.GNU_FORMAT) as new_tar:
							# Copy files from old archive to the new archive
							for member in original_tar.getmembers():
								if member.name == file:
									# Skip the original file
									continue
								new_tar.addfile(member, fileobj=original_tar.extractfile(member.name))

							# Add the modified file
							new_tar.add(target, arcname=file)

						# Replace the original archive
						path = self.path
						os.remove(path)
						os.rename(new_tar_path, path)
				else:
					log.debug(f"{str(self)} File {file} (mode={mode}) was not updated.")

	def create_manifest(self, hash_type: str = "sha1"):
		"""
		Creates a manifest file, or updates if it already exists.

		:param hash_type: The hash function to use for generating file checksums. Accepts any `hashlib` hash functions.
		"""
		log.info(f"{str(self)} Creating manifest...")

		newContent = ""
		for file in self.files:
			if os.path.splitext(file)[1].lower() in [".mf"]:
				continue

			with self.open(file, mode="rb") as f:
				h = getattr(hashlib, hash_type.lower())()
				while True:
					data = f.read(65536)
					if not data:
						break
					h.update(data)
				digest = h.hexdigest()
				log.debug(f"{str(self)} Hash for {file}: {digest}")
				newContent = newContent + f"{hash_type.upper()}({file})= {digest}\n"
			
		# Write contents
		mf = os.path.splitext(self.descriptor_name)[0] + ".mf"
		with self.open(mf, mode="w") as f:
			f.write(newContent)

	def validate(self):
		"""
		Validates this virtual appliance file by checking that referenced files exist and that the manifest file (if exists) is correct.
		Raises an `OvfManifestError` if the validation fails.
		"""
		log.info(f"{str(self)} Validating...")

		manifest = self.manifest
		def check_manifest_value(f, filename):
			if manifest:
				if filename not in manifest:
					raise exceptions.OvfManifestError(self.path, f"Referenced file \"{filename}\" does not exist in the manifest")
				hashtype = manifest[filename][0]
				expected_digest = manifest[filename][1]
				h = getattr(hashlib, hashtype.lower())()
				while True:
					data = f.read(65536)
					if not data:
						break
					h.update(data)
				digest = h.hexdigest()
				log.debug(f"{str(self)} Expected digest: {expected_digest} (Actual digest: {digest})")
				if digest != expected_digest:
					raise exceptions.OvfManifestError(self.path, f"Manifest does not validate for {filename} (Actual: {digest}; Expected: {expected_digest})")

		with self.open(self.descriptor_name, mode="rb") as f:
			descriptor = XmlFile(f)
			f.seek(0)
			check_manifest_value(f, self.descriptor_name)

		file_ids = []
		for file in descriptor.root["References"][0]["File"]:
			file_ids.append(file.attributes['ovf:id'])
			filename = file.attributes["ovf:href"]

			if filename not in self._list_files():
				raise exceptions.OvfManifestError(self.path, f"Referenced file \"{filename}\" does not exist")

			with self.open(filename, mode="rb") as f:
				size = os.fstat(f.fileno()).st_size
				expected_size = file.attributes['ovf:size']
				log.debug(f"{str(self)} File {filename} expected size: {expected_size} (Actual size: {size})")
				if str(size) != str(expected_size):
					raise exceptions.OvfManifestError(self.path, f"Referenced file \"{filename}\" does not match stated size (Actual {expected_size}; Expected {size})")

				# Check the hash
				check_manifest_value(f, filename)
			
		# Check that disks are referenced properly
		for disk in descriptor.root["DiskSection"][0]["Disk"]:
			file_ref = disk.attributes['ovf:fileRef']
			if file_ref not in file_ids:
				raise exceptions.OvfManifestError(self.path, f"Disk \"{disk.attributes['ovf:fileRef']}\" does not have a reference file.")
				
	def as_ovf(self, path: typing.Optional[str], move: bool = False) -> 'OvfFile':
		"""
		Write this file as an OVF to the provided directory.
		If this is an OVA, the contents will be extracted to the target directory.
		If this is already an OVF, the files will simply be copied to the target directory.

		:param path: The path to the directory in which to place the OVF. If `None`, this will be the same directory containing this file.
		:param move: Whether or not the move the files instead of copying them (delete original files). If `True`, the path for this object will be updated as well.

		:return: An `OvfFile` object for the new OVF.
		"""
		assert isinstance(path, str) or path is None, "path must be a string or None"
		assert isinstance(move, bool), "move must be a boolean"

		log.info(f"{str(self)} Converting to OVF at {path} (move={move})")

		if not self.is_archive and path is None and move == True:
			# Already an OVF, nothing to do
			return self

		if path is None:
			path = os.path.dirname(self.path)

		path = os.path.abspath(path)
		if not os.path.isdir(path):
			raise NotADirectoryError(f"{path} does not refer to an existing directory")

		# Ensure that there are no file conflicts in the target directory
		for file in self.files:
			p = os.path.join(path, file)
			if os.path.exists(p):
				raise FileExistsError(f"{p} already exists")

		# Create the copy
		new_path = os.path.join(path, self.descriptor_name)
		if self.is_archive:
			# Extract the archive
			log.debug(f"{str(self)} Extracting to {new_path}")
			with tarfile.open(self.path, "r") as tar:
				tar.extractall(path)
			if move:
				os.remove(self.path)
		else:
			# Already an OVF, copy the files
			dirname = os.path.dirname(self.path)
			for file in self.files:
				src = os.path.join(dirname, file)
				dst = os.path.join(path, file)
				if os.path.exists(src):
					if move:
						log.debug(f"{str(self)} Moving {src} to {dst}")
						os.rename(src, dst)
					else:
						log.debug(f"{str(self)} Copying {src} to {dst}")
						shutil.copy2(src, dst)

		if move:
			self._path = new_path
		return OvfFile(new_path)

	def as_ova(self, path: typing.Optional[str], move: bool = False) -> 'OvfFile':
		"""
		Write this file as an OVA to the provided directory.
		If this is already an OVA, this will simply be copied to the target directory
		If this is an OVF, the files will be added as a new archive in the target directory.

		:param path: The path to the directory in which to place the OVA. If `None`, this will be the same directory containing this file.
		:param move: Whether or not the move the files instead of copying them (delete original files). If `True`, the path for this object will be updated as well.

		:return: An `OvfFile` object for the new OVA.
		"""
		assert isinstance(path, str) or path is None, "path must be a string"
		assert isinstance(move, bool), "move must be a boolean"

		log.info(f"{str(self)} Converting to OVA at {path} (move={move})")

		if self.is_archive and path is None and move == True:
			# Already an OVA, nothing to do
			return self

		if path is None:
			path = os.path.dirname(self.path)

		path = os.path.abspath(path)
		if not os.path.isdir(path):
			raise NotADirectoryError(f"{path} does not refer to an existing directory")

		# Ensure that there are no file conflicts in the target directory
		new_path = os.path.join(path, f"{self.name}.ova")
		if os.path.exists(new_path):
			raise FileExistsError(f"{new_path} already exists")

		# Create the copy
		if self.is_archive:
			if move:
				log.debug(f"{str(self)} Moving {self.path} to {new_path}")
				os.rename(self.path, new_path)
			else:
				log.debug(f"{str(self)} Copying {self.path} to {new_path}")
				shutil.copy2(self.path, new_path)
		else:
			# This is an OVF, add the files under a new archive
			dirname = os.path.dirname(self.path)
			with tarfile.open(new_path, "w", format=tarfile.GNU_FORMAT) as tar:
				for file in self.files:
					src = os.path.join(dirname, file)
					log.debug(f"{str(self)} Adding {src} to {new_path}")
					tar.add(src, arcname=file)
					if move:
						log.debug(f"{str(self)} Removing {src}")
						os.remove(src)
		
		if move:
			self._path = new_path
		return OvfFile(new_path)

	def remove(self):
		"""
		Delete this file and any associated files.
		"""
		log.info(f"{str(self)} Removing...")

		if self.is_archive:
			log.debug(f"{str(self)} Removing {self.path}")
			os.remove(self.path)
		else:
			dirname = os.path.dirname(self.path)
			for file in self.files:
				path = os.path.join(dirname, file)
				log.debug(f"{str(self)} Removing {path}")
				os.remove(path)

	def rename(self, new_name: str):
		"""
		Rename this virtual appliance and its files. The update will happen in-place.
		Files after the the rename will follow the convention `{new_name}_file{num}` or `{new_name}_disk{num}`
		"""
		assert isinstance(new_name, str), "new_name must be a string"

		log.info(f"{str(self)} Renaming to {new_name}...")

		with tempfile.TemporaryDirectory(prefix="vapp-rename") as tmpdir:
			# In order to avoid having two separate functions for renaming OVF and OVAs, we'll create a common API
			# by working with the raw files in a temporary directory. If this is an OVF, we simply copy the files to
			# the temporary directory, and if this is an OVA we extract the files instead.
			# Before exiting this function, we'll replace the original file(s)
			# This has the added benefit of ensuring that the original files are not touched until the very end
			# i.e. the original files won't be modified if this function fails
			tmpovf = self.as_ovf(tmpdir, move=False)
			create_manifest = False
			if tmpovf.manifest_name:
				# Remove the manifest as it will become invalid
				# We'll re-create it later
				create_manifest = True
				temp_manifest_path = os.path.join(tmpdir, tmpovf.manifest_name)
				log.debug(f"{str(self)} Removing {temp_manifest_path}...")
				os.remove(temp_manifest_path)

			with open(os.path.join(tmpdir, tmpovf.descriptor_name)) as f:
				descriptor = XmlFile(f)

			old_value = descriptor.root["VirtualSystem"][0].attributes['ovf:id']
			log.debug(f"{str(self)} Setting VirtualSystem ID ({old_value}) to {new_name}")
			descriptor.root["VirtualSystem"][0].attributes['ovf:id'] = new_name

			old_value = descriptor.root["VirtualSystem"][0]["Name"][0].text
			log.debug(f"{str(self)} Setting VirtualSystem Name ({old_value}) to {new_name}")
			descriptor.root["VirtualSystem"][0]["Name"][0].text = new_name

			old_value = descriptor.root["VirtualSystem"][0]["VirtualHardwareSection"][0]["System"][0]["vssd:VirtualSystemIdentifier"][0].text
			log.debug(f"{str(self)} Setting VirtualSystemIdentifier ({old_value}) to {new_name}")
			descriptor.root["VirtualSystem"][0]["VirtualHardwareSection"][0]["System"][0]["vssd:VirtualSystemIdentifier"][0].text = new_name
			
			# Update files
			# The standard naming convention is {Name}_file{num} or {Name}_disk{num}
			# The rename will enforce this naming convention, even if the original files did not follow it
			num_files = 0
			num_disks = 0
			disk_file_ids = [ disk["fileRef"] for disk in descriptor.root["DiskSection"][0]["Disk"] ]
			for file in descriptor.root["References"][0]["File"]:
				# Update href
				old_href = file.attributes["ovf:href"]
				extension = os.path.splitext(old_href)[1]
				new_href = ""
				if file.attributes["ovf:id"] in disk_file_ids:
					# This is a disk
					new_href = f"{new_name}_disk{num_disks+1}{extension}"
					num_disks += 1
				else:
					new_href = f"{new_name}_file{num_files+1}{extension}"
					num_files += 1

				log.debug(f"{str(self)} Setting file {file.attributes['ovf:id']} href {file.attributes['ovf:href']} to {new_href}")
				file.attributes["ovf:href"] = new_href

				src = os.path.join(tmpdir, old_href)
				dst = os.path.join(tmpdir, new_href)
				log.debug(f"{str(self)} Renaming {src} to {dst}")
				os.rename(src, dst)
			
			# Write the descriptor
			temp_descriptor_path = os.path.join(tmpdir, tmpovf.descriptor_name)
			log.debug(f"{str(self)} Writing new descriptor to {temp_descriptor_path}")
			with open(temp_descriptor_path, "w") as f:
				f.write(descriptor.xml(pretty_print=True, xml_declaration=True))

			# Rename the OVF file itself
			src = os.path.join(tmpdir, tmpovf.descriptor_name)
			dst = os.path.join(tmpdir, f"{new_name}.ovf")
			log.debug(f"{str(self)} Renaming descriptor {src} to {dst}")
			os.rename(src, dst)
			tmpovf = OvfFile(dst)

			# If the manifest existed re-create it under the correct name
			# Note: this has to be done last to ensure the hashes are correct
			if create_manifest:
				tmpovf.create_manifest()

			# Move the modified files to the correct location and delete the originals
			dirname = os.path.dirname(self.path)
			if self.is_archive:
				tmpovf.as_ova(dirname, move=True)
			else:
				tmpovf.as_ovf(dirname, move=True)
			self.remove()
			self._path = tmpovf.path

	def rename_network(self, old_network_name: str, new_network_name: str):
		"""
		Rename a network in this OVF or OVA. The update will happen in-place.
		If the network is not found in the OVF, an exception will be raised.

		:param old_network_name: The name of the old network to update.
		:param new_network_name: The new name of the network.
		"""
		assert isinstance(old_network_name, str), "old_network_name must be a string"
		assert isinstance(new_network_name, str), "new_network_name must be a string"

		log.info(f"{str(self)} Renaming network {old_network_name} to {new_network_name}...")
		with self.open_descriptor() as descriptor:
			if len(descriptor.root["NetworkSection"]) == 0:
				raise exceptions.OvfFileError(self.path, f"OVF file does not contain a network section")

			for ovf_network in descriptor.root["NetworkSection"][0]["Network"]:
				old_value =  ovf_network.attributes["ovf:name"]
				if old_value != old_network_name:
					continue

				log.debug(f"{str(self)} Setting Network Name ({old_value}) to {new_network_name}")
				ovf_network.attributes["ovf:name"] = new_network_name

				old_value = ovf_network["Description"][0].text
				new_value = ovf_network["Description"][0].text.replace(old_network_name, new_network_name)
				log.debug(f"{str(self)} Setting Network Description ({old_value}) to {new_value}")
				ovf_network["Description"][0].text = new_value
				break
			else:
				raise exceptions.OvfFileError(self.path, f"Could not find network \"{old_network_name}\"")

			# Update network hardware
			for hardware_item in descriptor.root["VirtualSystem"][0]["VirtualHardwareSection"][0]["Item"]:
				if hardware_item["rasd:ResourceType"][0].text.strip() not in ["10", "11"]: # 10 = Ethernet Adapter; 11 = Other Network Adapter
					continue
				old_value = hardware_item["rasd:Connection"][0].text
				if old_value != old_network_name:
					continue

				log.debug(f"{str(self)} Setting Connection ({old_value}) to {new_network_name}")
				hardware_item["rasd:Connection"][0].text = new_network_name

				old_value = hardware_item["rasd:Description"][0].text
				new_value = hardware_item["rasd:Description"][0].text.replace(old_network_name, new_network_name)
				log.debug(f"{str(self)} Setting Connection Description ({old_value}) to {new_network_name}")
				hardware_item["rasd:Description"][0].text = new_value
				break
			else:
				raise exceptions.OvfFileError(self.path, f"Could not find network \"{old_network_name}\"")

		if self.manifest_name:
			# Fix the manifest
			self.create_manifest()

	def set_config(self, key: str, value: typing.Union[str, bool], required: bool = False, extraconfig=False):
		"""
		Set a config entry (a <Config> tag) in the OVF. If the entry does not exist, it will be created.

		:param key: The entry key.
		:param value: The entry value.
		:param required: Whether or not the entry is set to be required.
		:param extraconfig: Whether or not this is an extra-config entry (an <ExtraConfig> tag) rather than a standard config entry.
		"""
		if isinstance(value, bool):
			value = "true" if value else "false"
		tag = "vmw:ExtraConfig" if extraconfig else "vmw:Config"

		root = self.descriptor.root["VirtualSystem"][0]["VirtualHardwareSection"][0]
		matching = [config for config in root[tag] if config.attributes["vmw:key"] == key ]

		config = None
		if len(matching) != 0:
			config = matching[0]
		else:
			config = root.append(tag)
		config.attributes["ovf:required"] = "true" if required else "false"
		config.attributes["vmw:key"] = key
		config.attributes["vmw:value"] = value

	def remove_config(self, key: str, extraconfig=False):
		"""
		Remove a config entry (a <Config> tag) in the OVF. If the entry does not exist, this does nothing.

		:param key: The entry key.
		:param extraconfig: Whether or not this is an extra-config entry (an <ExtraConfig> tag) rather than a standard config entry.
		"""
		tag = "vmw:ExtraConfig" if extraconfig else "vmw:Config"
		entries = self.descriptor.root["VirtualSystem"][0]["VirtualHardwareSection"][0][tag]
		for config in entries:
			if config.attributes["vmw:key"] == key:
				config.remove()

	def _list_files(self):
		"""
		List files in this OVF's parent directory, or a list of files contained in the OVA archive.

		:return: A list of file names.
		"""
		if not self.is_archive:
			return os.listdir(os.path.dirname(self.path))
		with tarfile.open(self.path, "r") as tar:
			return tar.getnames()

	def __str__(self):
		return f"<{type(self).__name__} at {self._path}>"

	def __repr__(self):
		return str(self)
		