from esxi_utils.vm.hardware.device import VirtualDevice, VirtualDeviceList
from esxi_utils.util import log
import pyVmomi
import typing


class VirtualVideoCardList(VirtualDeviceList):
	"""
	The list of all virtual video cards on a Virtual Machine.
	"""
	def __iter__(self) -> typing.Iterator['VirtualVideoCard']:
		cards = [ dev for dev in super().__iter__() if isinstance(dev, VirtualVideoCard) ]
		# cards.sort(key=lambda x: int(re.search(r"\d+", x.label).group(0)))
		return iter(cards)

	def __getitem__(self, index) -> 'VirtualVideoCard':
		return self.items[index]

	@property
	def items(self) -> 'VirtualVideoCard':
		"""
		A list of all items
		"""
		return list(self)


class VirtualVideoCard(VirtualDevice):
    @property
    def videoRamSizeKB(self) -> int:
        """
        The current size of the video card VRAM
        """
        return self._obj.videoRamSizeInKB
	
    @property
    def graphicsMemorySizeKB(self) -> int:
        """
        The current size of the 3D graphics memory
        """
        return self._obj.graphicsMemorySizeInKB
    
    @property
    def enable3D(self) -> bool:
        """
        Whether or not (3D) graphics are currently enabled on this video card
        """
        return self._obj.enable3DSupport
    
    @property
    def use3Drenderer(self) -> str:
        """
        Returns a string such as 'automatic'
        """
        return self._obj.use3dRenderer
    
    @property
    def useAutoDetect(self) -> bool:
        """
        When true: VM will auto-detect graphic settings from the VM. When false: depends on custom settings as set by the user in the GUI
        """
        return self._obj.useAutoDetect

    @property
    def numDisplays(self) -> int:
        """
        The number of displays connected to this video card
        """
        return self._obj.numDisplays
    
    def createVideoCardEditSpec(self) -> pyVmomi.vim.vm.device.VirtualDeviceSpec:
        """
        The boilerplate template object that will be passed to 'edit'/reconfigure the video card.
        All video card setter tasks will need this base object.

        :returns: the pyVmomi object needed to reconfigure the video card
        """
        video_card_spec = pyVmomi.vim.vm.device.VirtualDeviceSpec()
        video_card_spec.operation = pyVmomi.vim.vm.device.VirtualDeviceSpec.Operation.edit
        video_card_spec.device = self._obj
        return video_card_spec

    def videoCardReconfigureTask(self, video_card_spec: pyVmomi.vim.vm.device.VirtualDeviceSpec):
        """
        Nests the video_card_spec inside the generate configuration spec needed by pyVmomi. Executes the video card reconfiguration/'edit' task. Waits for the task to finish.
        """
        spec = pyVmomi.vim.vm.ConfigSpec()
        spec.deviceChange = [video_card_spec]
        self._vm._client._wait_for_task(
            self._vm._vim_vm.ReconfigVM_Task(spec=spec)
        )
    
    @useAutoDetect.setter
    def useAutoDetect(self, use: bool):
        """
        Set the auto detect flag for this video card.

        :param use: When true: VM will auto-detect graphic settings from the VM. When false: depends on custom settings as set by the user in the GUI
        """
        log.info(f"{str(self)} Updating auto-detect to: {use}")
        
        video_card_spec = self.createVideoCardEditSpec()
        video_card_spec.device.useAutoDetect = use
        self.videoCardReconfigureTask(video_card_spec)

    @graphicsMemorySizeKB.setter
    def graphicsMemorySizeKB(self, size: int):
        """
        Set the (3D) graphics memory size for this video card. An error may occur if the size isn't supported by the VM or ESXi itself.
        The VM must be turned off to change this setting.
        THIS VALUE IS NOT THE ONE SHOWN IN THE ESXI UI (see 'videoRamSizeKB' for the VRAM value shown as 'Total Video Memory' in the UI.)
        You should only try to set the size of the video card if 'useAutoDetect' is false.

        :param size: The size in KB (KiloBytes) to set the video card 'graphics' memory to (e.g. 1024 KB is 1 MB)
        """
        log.info(f"{str(self)} Updating graphics memory size to: {size}")
        
        video_card_spec = self.createVideoCardEditSpec()
        video_card_spec.device.graphicsMemorySizeInKB = size
        self.videoCardReconfigureTask(video_card_spec)

    @videoRamSizeKB.setter
    def videoRamSizeKB(self, size: int):
        """
        Set the VRAM size for this video card. An error may occur if the size isn't supported by the VM or ESXi itself. This is the 'Total Video Memory' field as shown in the ESXi UI.
        The VM must be turned off to change this setting.
        You should only try to set the size of the video card if 'useAutoDetect' is false.

        :param size: The size in KB (KiloBytes) to set the video card VRAM to (e.g. 1024 KB is 1 MB)
        """
        log.info(f"{str(self)} Updating VRAM size to: {size}")
        
        video_card_spec = self.createVideoCardEditSpec()
        video_card_spec.device.videoRamSizeInKB = size
        self.videoCardReconfigureTask(video_card_spec)

    @enable3D.setter
    def enable3D(self, enabled: bool):
        """
        Set 3D support on the video card to be either enabled or disabled.
        The VM must be turned off to change this setting.
        You should only try to change this value if the video card 'useAutoDetect' field is false.

        :param enabled: Whether to set 3D to enabled on this video card or not
        """
        log.info(f"{str(self)} Updating 3D status to: {enabled}")
        
        video_card_spec = self.createVideoCardEditSpec()
        video_card_spec.device.enable3DSupport = enabled
        self.videoCardReconfigureTask(video_card_spec)

    @use3Drenderer.setter
    def use3Drenderer(self, renderer_name: str):
        """
        Set the name of the 3D renderer to use.
        You should only try to change this value if the video card 'useAutoDetect' field is false.

        :param renderer_name: The name of the renderer to use (options appear to be: Automatic, Hardware, Software)
        """
        log.info(f"{str(self)} Updating 3D renderer to: {renderer_name}")
        
        video_card_spec = self.createVideoCardEditSpec()
        video_card_spec.device.use3Drenderer = renderer_name
        self.videoCardReconfigureTask(video_card_spec)

    @numDisplays.setter
    def numDisplays(self, amount: int):
        """
        Set the number of displays connected to this video card.
        You should only try to set the size of the video card if 'useAutoDetect' is false.

        :param amount: the number of displays to connect to this video card (options in the UI are 1 through 10)
        """
        log.info(f"{str(self)} Updating number of displays to: {amount}")
        
        video_card_spec = self.createVideoCardEditSpec()
        video_card_spec.device.numDisplays = amount
        self.videoCardReconfigureTask(video_card_spec)

    def __str__(self):
        if self.useAutoDetect:
            return f"<{type(self).__name__} with auto-detect video settings set to 'True' for VM='{self._vm.name}'>"
        return f"<{type(self).__name__} with custom VRAM setting: '{self.videoRamSizeKB} KB' for VM='{self._vm.name}'>" 
