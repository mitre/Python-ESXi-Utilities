from esxi_utils.util import log, exceptions
from datetime import datetime
import typing

if typing.TYPE_CHECKING:
	from esxi_utils.vm.virtualmachine import VirtualMachine

class SnapshotList:
	"""
	Class representing the snapshots for the given VirtualMachine.

	:param vm: A `VirtualMachine` object
	"""
	def __init__(self, vm: 'VirtualMachine'):
		self._vm = vm
		self._vim_vm = vm._vim_vm

	def __iter__(self) -> typing.List['Snapshot']:
		if self.root is None:
			return iter([])
		return iter(self.root.flattened)

	def __getitem__(self, name_or_id: typing.Union[str, int]) -> 'Snapshot':
		return self.get(name_or_id)

	def find(self, name_or_id: typing.Union[str, int]) -> typing.Union['Snapshot', None]:
		"""
		Find a snapshot by name or ID.
		If multiple snapshots match, this will raise a `MultipleSnapshotsFoundError` exception.

		:param name_or_id: The snapshot name (string) or ID (int).

		:return: A `Snapshot` object for the requested snapshot, or `None` if the snapshot was not found.
		"""
		assert isinstance(name_or_id, (str, int))
		found = [ s for s in self if s.name == name_or_id or s.id == name_or_id ]
		if len(found) == 0:
			return None
		if len(found) > 1:
			raise exceptions.MultipleSnapshotsFoundError(self._vm, name_or_id)
		return found[0]

	def get(self, name_or_id: typing.Union[str, int]) -> 'Snapshot':
		"""
		Find a snapshot by name or ID and raise an exception if not found.
		If multiple snapshots match, this will raise a `MultipleSnapshotsFoundError` exception.

		:param name_or_id: The snapshot name (string) or ID (int).

		:return: A `Snapshot` object for the requested snapshot
		"""
		snapshot = self.find(name_or_id)
		if snapshot is None:
			raise exceptions.SnapshotNotFoundError(self._vm, name_or_id)
		return snapshot

	@property
	def root(self) -> typing.Union['Snapshot', None]:
		"""
		The root snapshot.
		"""
		snapshot_data = self._vim_vm.snapshot
		if snapshot_data is None:
			return None
		return Snapshot(vm=self._vm, id=snapshot_data.rootSnapshotList[0].id)

	@property
	def exists(self) -> bool:
		"""
		Returns whether or not any snapshots exist on this VirtualMachine.

		:return: A boolean whether or not this VirtualMachine has snapshots.
		"""
		return len(list(self)) != 0

	@property
	def current(self) -> typing.Union['Snapshot', None]:
		"""
		Get the current snapshot of this VM.

		:return: A `Snapshot` object for the current snapshot, or `None` if there is no current snapshot.
		"""
		current_snapshot = self._vim_vm.snapshot.currentSnapshot
		current = [ s for s in self if str(s._obj.snapshot) == str(current_snapshot) ]
		if len(current) == 0:
			return None
		return current[0]

	def remove_all(self):
		"""
		Remove all snapshots from this VirtualMachine.
		"""
		if self.root is None:
			return
		self.root.remove(remove_children=True)

	def create(self, name: str, description: str = "", include_memory: bool = False, quiesce: bool = False):
		"""
		Create a new snapshot of this VirtualMachine.

		:param name: 
			The name for this snapshot. The name need not be unique for this virtual machine.
		:param description: 
			A description for this snapshot.
		:param include_memory: 
			If `True`, a dump of the internal state of the virtual machine (basically a memory dump) is included in the snapshot. 
			Memory snapshots consume time and resources, and thus take longer to create.
			When `False`, the power state of the snapshot is set to powered off.
		:param quiesce:
			If `True` and the virtual machine is powered on when the snapshot is taken, VMware Tools is used to quiesce the file system in the virtual machine. 
			This assures that a disk snapshot represents a consistent state of the guest file systems. 
			If the virtual machine is powered off or VMware Tools are not available, the quiesce flag is ignored. 
		"""
		log.info(f"{str(self._vm)} Creating snapshot \"{name}\" (description = \"{description}\", include memory = {str(include_memory)}, quiesce = {str(quiesce)})")
		self._vm._client._wait_for_task(
			self._vim_vm.CreateSnapshot_Task(name=name, description=description, memory=include_memory, quiesce=quiesce)
		)

	def __str__(self):
		return f"<{type(self).__name__} for {self._vm.name} ({len(list(self))} snapshots)>"
	
	def __repr__(self):
		return self.__str__()


class Snapshot:
	"""
	Class representing a single snapshot for a VirtualMachine.
	"""
	def __init__(self, vm: 'VirtualMachine', id: int):
		self._vm = vm
		self._id = id

	@property
	def id(self) -> int:
		"""
		The snapshot ID.
		"""
		return self._id

	@property
	def name(self) -> str:
		"""
		The snapshot name.
		"""
		return self._obj.name

	@property
	def description(self) -> str:
		"""
		The snapshot description.
		"""
		return self._obj.description

	@property
	def createtime(self):
		"""
		The snapshot ID.
		"""
		return datetime.fromisoformat(str(self._obj.createTime))

	@property
	def state(self) -> str:
		"""
		The power state of the virtual machine when this snapshot was taken. 
		"""
		return self._obj.state

	@property
	def powered_on(self) -> bool:
		"""
		Whether the power state of this snapshot is set to on.
		"""
		return self.state == "poweredOn"

	@property
	def quiesced(self) -> bool:
		"""
		Flag to indicate whether or not the snapshot was created with the "quiesce" option, ensuring a consistent state of the file system.
		"""
		return self._obj.quiesced

	@property
	def children(self) -> typing.List['Snapshot']:
		"""
		Child snapshots of this snapshot.
		"""
		return [ Snapshot(vm=self._vm, id=child.id) for child in self._obj.childSnapshotList ]

	@property
	def flattened(self) -> typing.List['Snapshot']:
		"""
		A flat list of snapshot objects containing this snapshot and its children.
		"""
		child_list = list()
		for child in self.children:
			child_list.extend(child.flattened)
		return [self, *child_list]

	def remove(self, remove_children: bool = False):
		"""
		Remove this snapshot (and optionally its children) from the VM.

		:param remove_children: Whether or not to remove children snapshots.
		"""
		self._vm._client._wait_for_task(
			self._obj.snapshot.RemoveSnapshot_Task(removeChildren=remove_children)
		)

	def revert(self, suppress_power_on: bool = False):
		"""
		Revert to this snapshot.

		:param suppress_power_on: If set to true, the virtual machine will not be powered on regardless of the power state when the snapshot was created.
		"""
		self._vm._client._wait_for_task(
			self._obj.snapshot.RevertToSnapshot_Task(suppressPowerOn=suppress_power_on)
		)

	@property
	def _obj(self):
		snapshot_data =  []
		if self._vm._vim_vm.snapshot:
			snapshot_data.extend(self._vm._vim_vm.snapshot.rootSnapshotList)
		for snapshot in snapshot_data:
			if snapshot.id == self.id:
				return snapshot
			snapshot_data.extend(snapshot.childSnapshotList)
		raise exceptions.SnapshotNotFoundError(self._vm, self.id)

	def __str__(self):
		return f"<{type(self).__name__} \"{self.name}\" (ID {self.id}) for {self._vm.name} ({len(self.children)} children)>"
	
	def __repr__(self):
		return self.__str__()

	