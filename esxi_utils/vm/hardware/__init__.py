from esxi_utils.vm.hardware.cdrom import VirtualCdrom, VirtualCdromList
from esxi_utils.vm.hardware.device import VirtualDevice, VirtualDeviceList
from esxi_utils.vm.hardware.disk import VirtualDisk, VirtualDiskList
from esxi_utils.vm.hardware.floppy import VirtualFloppy, VirtualFloppyList
from esxi_utils.vm.hardware.nic import VirtualNIC, VirtualNICList
from esxi_utils.vm.hardware.video_card import VirtualVideoCard, VirtualVideoCardList

__all__ = [
	"VirtualCdrom",
	"VirtualDevice",
	"VirtualDisk",
	"VirtualFloppy",
	"VirtualNIC",
    "VirtualVideoCard"
]