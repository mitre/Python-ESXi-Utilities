# example usage (log file):
################
# from esxi_utils.client import ESXiClient
# client: ESXiClient = ESXiClient(hostname=esxi_host, username=esxi_user, password=esxi_pass, verify_ssl=False)
# vm = client.vms.get(vm_name)
#
# serial_file_path: str = f"logs/{vm.name}-serial.log"
# full_serial_file_path: str = f"[{esxi_datastore}] {serial_file_path}"
#
# serial_port = vm.serial_ports.add_file_backing(
# 	filepath=full_serial_file_path,
# 	yield_on_poll=True,
# 	start_connected=True,
# 	allow_guest_control=True,
# 	idempotent=True,
# )
################

# example usage (URI backing):
################
# # 1) ESXi listens (server mode). You connect from your terminal:
# #    $ nc <esxi_host> 7000
# #    or
# #    $ telnet <esxi_host> 7000
# serial_uri: str = "tcp://:7000"
# sp_server = vm.serial_ports.add_uri_backing(
# 	service_uri=serial_uri,
# 	direction="server",
# 	yield_on_poll=True,
# 	start_connected=True,
# 	allow_guest_control=True,
# 	idempotent=True,
# )
# print(sp_server)
# print(sp_server.uri_service, sp_server.uri_direction)

# # 2) ESXi connects outward (client mode) to a listener you run elsewhere:
# #    On your workstation/server:
# #      $ nc -lv 7001
# serial_uri_client: str = "tcp://10.0.0.10:7001"
# sp_client = vm.serial_ports.add_uri_backing(
# 	service_uri=serial_uri_client,
# 	direction="client",
# 	yield_on_poll=True,
# 	start_connected=True,
# 	allow_guest_control=True,
# 	idempotent=True,
# )
# print(sp_client)
################

from esxi_utils.vm.hardware.device import VirtualDevice, VirtualDeviceList
from esxi_utils.datastore import DatastoreFile
from esxi_utils.util import log, exceptions
import pyVmomi
import typing
import re

if typing.TYPE_CHECKING:
    from esxi_utils.vm.virtualmachine import VirtualMachine


class VirtualSerialPortList(VirtualDeviceList):
    """
    The list of all virtual Serial Ports on a Virtual Machine.
    """

    def __iter__(self) -> typing.Iterator["VirtualSerialPort"]:
        ports: typing.List[VirtualDevice] = [
            dev for dev in super().__iter__() if isinstance(dev, VirtualSerialPort)
        ]

        # Sort by number in label when possible (e.g. "Serial port 1")
        def _sort_key(p: "VirtualSerialPort") -> int:
            m: typing.Optional[re.Match[str]] = re.search(r"\d+", p.label or "")
            return int(m.group(0)) if m else 999999

        ports.sort(key=_sort_key)
        return iter(typing.cast(typing.List["VirtualSerialPort"], ports))

    @property
    def items(self) -> typing.List["VirtualSerialPort"]:
        """
        A list of all items
        """
        return list(self)

    def add_file_backing(
        self,
        filepath: typing.Union["DatastoreFile", str],
        yield_on_poll: bool = True,
        start_connected: bool = True,
        allow_guest_control: bool = True,
        idempotent: bool = True,
    ) -> "VirtualSerialPort":
        """
        Add a serial port backed by a datastore file.

        Arguments:
        - filepath: typing.Union["DatastoreFile", str]
            The datastore location where ESXi will write the serial output log.

            Acceptable forms:
            - DatastoreFile:
                A DatastoreFile whose .path is already in ESXi datastore notation, e.g.
                "[datastore1] logs/vm-serial.log"
            - str:
                A datastore-path string in that same notation, e.g.
                "[datastore1] logs/vm-serial.log"

            This value is applied to:
                vim.vm.device.VirtualSerialPort.FileBackingInfo.fileName

        - yield_on_poll: bool = True
            Sets the serial device's yieldOnPoll behavior (vim.vm.device.VirtualSerialPort.yieldOnPoll).

            When True, the virtual device yields CPU when the guest polls the serial port while no data
            is available. This can reduce CPU usage for guests that aggressively poll the serial port.

            This corresponds to Ansible's:
                yield_on_poll: true

        - start_connected: bool = True
            Sets connectable.startConnected (vim.vm.device.VirtualDevice.ConnectInfo.startConnected).

            When True, ESXi will attempt to connect the serial device automatically when the VM powers on.
            When False, the serial device starts disconnected and must be connected manually.

            For file-backed logging you typically want True so logging begins immediately at boot.

        - allow_guest_control: bool = True
            Sets connectable.allowGuestControl (vim.vm.device.VirtualDevice.ConnectInfo.allowGuestControl).

            When True, the guest is permitted (where supported) to connect/disconnect the serial device.
            When False, connection state is controlled only by ESXi/vSphere configuration/UI/API.

        - idempotent: bool = True
            When True, the method checks whether a serial port already exists with the same file backing
            path and returns that existing port rather than adding a duplicate.

            When False, the method will always attempt to add a new serial port, which can create
            duplicates if called multiple times with the same filepath.
        """
        file: DatastoreFile
        if isinstance(filepath, str):
            file = DatastoreFile.parse(self._vm._client, filepath)
        elif isinstance(filepath, DatastoreFile):
            file = filepath
        else:
            raise TypeError(
                'filepath must be a DatastoreFile or datastore-path string like "[datastore] logs/x.log"'
            )

        if idempotent:
            p: VirtualSerialPort
            for p in self:
                existing_file: typing.Optional[DatastoreFile] = p.file
                if existing_file is not None and existing_file.path == file.path:
                    return p

        log.info(f"{str(self)} Adding serial port with file backing: {file.path}")

        port_spec: pyVmomi.vim.vm.device.VirtualDeviceSpec = (
            pyVmomi.vim.vm.device.VirtualDeviceSpec()
        )
        port_spec.operation = pyVmomi.vim.vm.device.VirtualDeviceSpec.Operation.add
        port_spec.device = pyVmomi.vim.vm.device.VirtualSerialPort()

        # Match Ansible yield_on_poll
        port_spec.device.yieldOnPoll = bool(yield_on_poll)

        # File backing: "[datastore] some/path.log"
        port_spec.device.backing = (
            pyVmomi.vim.vm.device.VirtualSerialPort.FileBackingInfo()
        )
        port_spec.device.backing.fileName = file.path

        port_spec.device.connectable = pyVmomi.vim.vm.device.VirtualDevice.ConnectInfo()
        port_spec.device.connectable.allowGuestControl = bool(allow_guest_control)
        port_spec.device.connectable.startConnected = bool(start_connected)
        port_spec.device.connectable.connected = False

        added: VirtualDevice = self._add_device(port_spec)
        return typing.cast("VirtualSerialPort", added)

    def add_uri_backing(
        self,
        service_uri: str,
        direction: str = "server",
        yield_on_poll: bool = True,
        start_connected: bool = True,
        allow_guest_control: bool = True,
        idempotent: bool = True,
        proxy_uri: typing.Optional[str] = None,
        proxy_direction: typing.Optional[str] = None,
    ) -> "VirtualSerialPort":
        """
        Add a serial port backed by a network URI (ESXi 7+ supported).

        Recommended (raw TCP):
        - Listen on ESXi host:
            service_uri="tcp://:7000", direction="server"
        - Connect outward:
            service_uri="tcp://10.0.0.10:7000", direction="client"

        Also commonly accepted:
        - "telnet://:7000" (adds telnet semantics)

        Notes:
        - ESXi firewall must allow the chosen port for inbound "server" mode.
        - proxy_uri/proxy_direction are typically used in vCenter/proxy scenarios; usually None on standalone ESXi.

        Arguments:
        - service_uri: str
            The URI that defines how the serial port connects over the network.

            Common ESXi 7+ forms:
            - "tcp://:7000"
                ESXi listens on port 7000 (when direction="server")
            - "tcp://10.0.0.10:7000"
                ESXi connects to 10.0.0.10:7000 (when direction="client")
            - "telnet://..."
                Similar, but with telnet negotiation semantics

            This value is applied to:
                vim.vm.device.VirtualSerialPort.URIBackingInfo.serviceURI

        - direction: str = "server"
            Controls whether ESXi listens locally or connects outward.
            This is applied to:
                vim.vm.device.VirtualSerialPort.URIBackingInfo.direction

            Valid values:
            - "server"
                ESXi listens; you connect to the ESXi host/port from your terminal/tool (e.g. nc/telnet).
            - "client"
                ESXi initiates an outbound connection to the host/port specified in service_uri.

        - yield_on_poll: bool = True
            Sets vim.vm.device.VirtualSerialPort.yieldOnPoll.

            When True, reduces CPU usage for guests that poll the serial device with no data available.

        - start_connected: bool = True
            Sets connectable.startConnected (vim.vm.device.VirtualDevice.ConnectInfo.startConnected).

            When True, the serial connection is attempted automatically at VM power-on.
            When False, the serial device starts disconnected and must be connected manually.

        - allow_guest_control: bool = True
            Sets connectable.allowGuestControl (vim.vm.device.VirtualDevice.ConnectInfo.allowGuestControl).

            When True, the guest is permitted (where supported) to connect/disconnect the serial device.
            When False, only ESXi/vSphere configuration/UI/API controls connection state.

        - idempotent: bool = True
            When True, the method checks for an existing URI-backed serial port with a matching service_uri
            and direction (and, if provided, matching proxy settings) and returns it instead of adding a duplicate.

        - proxy_uri: typing.Optional[str] = None
            Optional proxy endpoint for the serial connection.
            Applied to:
                vim.vm.device.VirtualSerialPort.URIBackingInfo.proxyURI

            Usually None for standalone ESXi. Primarily relevant in proxied/vCenter-style workflows.

        - proxy_direction: typing.Optional[str] = None
            Optional proxy direction, typically "server" or "client".
            Applied to:
                vim.vm.device.VirtualSerialPort.URIBackingInfo.proxyDirection

            Usually left as None unless proxy_uri is set and your environment requires it.
        """
        assert (
            isinstance(service_uri, str) and len(service_uri.strip()) > 0
        ), "service_uri must be a non-empty string"
        service_uri_norm: str = service_uri.strip()

        direction_norm: str = direction.strip().lower()
        if direction_norm not in ["server", "client"]:
            raise ValueError("direction must be either 'server' or 'client'")

        if not (
            service_uri_norm.startswith("tcp://")
            or service_uri_norm.startswith("telnet://")
        ):
            raise ValueError(
                'service_uri must start with "tcp://" or "telnet://" for ESXi 7+ network serial ports'
            )

        if service_uri_norm.startswith("telnet://"):
            log.warning(
                "Serial port URI uses telnet://. For ESXi 7+ streaming, tcp:// is usually preferable."
            )

        if proxy_direction is not None:
            proxy_direction_norm: str = proxy_direction.strip().lower()
            if proxy_direction_norm not in ["server", "client"]:
                raise ValueError("proxy_direction must be either 'server' or 'client'")
        else:
            proxy_direction_norm = ""

        if idempotent:
            p: VirtualSerialPort
            for p in self:
                if p.uri_service is not None and p.uri_direction is not None:
                    if (
                        p.uri_service == service_uri_norm
                        and p.uri_direction.lower() == direction_norm
                    ):
                        if proxy_uri is None and proxy_direction is None:
                            return p
                        if (p.uri_proxy_service == proxy_uri) and (
                            (p.uri_proxy_direction or "").lower()
                            == proxy_direction_norm
                        ):
                            return p

        log.info(
            f"{str(self)} Adding serial port with URI backing: {service_uri_norm} (direction={direction_norm})"
        )

        port_spec: pyVmomi.vim.vm.device.VirtualDeviceSpec = (
            pyVmomi.vim.vm.device.VirtualDeviceSpec()
        )
        port_spec.operation = pyVmomi.vim.vm.device.VirtualDeviceSpec.Operation.add
        port_spec.device = pyVmomi.vim.vm.device.VirtualSerialPort()

        port_spec.device.yieldOnPoll = bool(yield_on_poll)

        backing: pyVmomi.vim.vm.device.VirtualSerialPort.URIBackingInfo = (
            pyVmomi.vim.vm.device.VirtualSerialPort.URIBackingInfo()
        )
        backing.serviceURI = service_uri_norm

        dir_enum: typing.Any = getattr(
            pyVmomi.vim.vm.device.VirtualSerialPort.URIBackingInfo, "Direction", None
        )
        if dir_enum is not None and hasattr(dir_enum, direction_norm):
            backing.direction = getattr(dir_enum, direction_norm)
        else:
            backing.direction = direction_norm

        if proxy_uri is not None:
            backing.proxyURI = proxy_uri
        if proxy_direction is not None:
            if dir_enum is not None and hasattr(dir_enum, proxy_direction_norm):
                backing.proxyDirection = getattr(dir_enum, proxy_direction_norm)
            else:
                backing.proxyDirection = proxy_direction_norm

        port_spec.device.backing = backing

        port_spec.device.connectable = pyVmomi.vim.vm.device.VirtualDevice.ConnectInfo()
        port_spec.device.connectable.allowGuestControl = bool(allow_guest_control)
        port_spec.device.connectable.startConnected = bool(start_connected)
        port_spec.device.connectable.connected = False

        added: VirtualDevice = self._add_device(port_spec)
        return typing.cast("VirtualSerialPort", added)


class VirtualSerialPort(VirtualDevice):
    @property
    def yield_on_poll(self) -> bool:
        return bool(getattr(self._obj, "yieldOnPoll", False))

    @yield_on_poll.setter
    def yield_on_poll(self, value: bool):
        log.info(f'{str(self)} Setting yieldOnPoll to "{value}"')

        device_spec: pyVmomi.vim.vm.device.VirtualDeviceSpec = (
            pyVmomi.vim.vm.device.VirtualDeviceSpec()
        )
        device_spec.operation = pyVmomi.vim.vm.device.VirtualDeviceSpec.Operation.edit
        device_spec.device = self._obj
        device_spec.device.yieldOnPoll = bool(value)

        spec: pyVmomi.vim.vm.ConfigSpec = pyVmomi.vim.vm.ConfigSpec()
        spec.deviceChange = [device_spec]
        self._vm._client._wait_for_task(self._vm._vim_vm.ReconfigVM_Task(spec=spec))

    @property
    def backing_type(self) -> str:
        b: typing.Any = getattr(self._obj, "backing", None)
        if isinstance(b, pyVmomi.vim.vm.device.VirtualSerialPort.FileBackingInfo):
            return "file"
        if isinstance(b, pyVmomi.vim.vm.device.VirtualSerialPort.URIBackingInfo):
            return "uri"
        return "other"

    @property
    def file(self) -> typing.Optional["DatastoreFile"]:
        b: typing.Any = getattr(self._obj, "backing", None)
        if not isinstance(b, pyVmomi.vim.vm.device.VirtualSerialPort.FileBackingInfo):
            return None
        return self._get_backing_file()

    @property
    def uri_service(self) -> typing.Optional[str]:
        b: typing.Any = getattr(self._obj, "backing", None)
        if not isinstance(b, pyVmomi.vim.vm.device.VirtualSerialPort.URIBackingInfo):
            return None
        return getattr(b, "serviceURI", None)

    @property
    def uri_direction(self) -> typing.Optional[str]:
        b: typing.Any = getattr(self._obj, "backing", None)
        if not isinstance(b, pyVmomi.vim.vm.device.VirtualSerialPort.URIBackingInfo):
            return None
        val: typing.Any = getattr(b, "direction", None)
        return str(val) if val is not None else None

    @property
    def uri_proxy_service(self) -> typing.Optional[str]:
        b: typing.Any = getattr(self._obj, "backing", None)
        if not isinstance(b, pyVmomi.vim.vm.device.VirtualSerialPort.URIBackingInfo):
            return None
        return getattr(b, "proxyURI", None)

    @property
    def uri_proxy_direction(self) -> typing.Optional[str]:
        b: typing.Any = getattr(self._obj, "backing", None)
        if not isinstance(b, pyVmomi.vim.vm.device.VirtualSerialPort.URIBackingInfo):
            return None
        val: typing.Any = getattr(b, "proxyDirection", None)
        return str(val) if val is not None else None

    def __str__(self):
        return (
            f"<{type(self).__name__}("
            f"backing={self.backing_type}, "
            f"file='{self.file}', "
            f"uri_service='{self.uri_service}', "
            f"uri_direction='{self.uri_direction}', "
            f"yieldOnPoll={self.yield_on_poll}"
            f") for VM='{self._vm.name}'>"
        )
