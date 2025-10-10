from esxi_utils.util import log, exceptions, usbkeycodes
import pyVmomi
import typing


if typing.TYPE_CHECKING:
    from esxi_utils.vm.virtualmachine import VirtualMachine

class USBHandler:
    """
    Handler class for using USB Scan codes on a VirtualMachine (replaces VNC key codes).

    :param vm:
        A `VirtualMachine` object
    """
    def __init__(self, vm: 'VirtualMachine'):
        self._vm = vm
        self._client = vm._client
        # this prefix appears in front of all the keys
        self._keycode_name_prefix = 'KEY_'
        # contains a mapping of 'key as char/string' -> 'key as usb scan code (hex)'
        self._keycode_map = USBHandler._create_keycode_maps(keycode_name_prefix=self._keycode_name_prefix)
        # when true, the values in the keycodes.json file are in all caps (else assumes all lowercase)
        self._keycode_caps = True

    def _prep_key(self, key: str):
        """
        Handles:
        - if the key needs to be paired with the 'shift' key
        - finds the USB scan code for the provided string key
        - throws a UsbScanCodeError exception if the scan code can't be found
        - converts the found HEX code into an ESXi keyboard code and then into an ESXi key object
        - applies the 'shift' modifier if needed to the key object

        :param key:
            The key (as a string) to send through the ESXi API (e.g. 'a').
        :return:
            the key object to press
        """
        # Do we need to pair this key press with a shift modifier ?
        modifiers = None
        needs_shift = True if key.isupper() else False
        if key in '~!@#$%^&*()_+{}|:"<>?':
            needs_shift = True
            key = USBHandler._get_base_key(key)
        if needs_shift:
            # leftShift is preferable over right (short circuits conditional)
            modifiers = USBHandler._create_key_modifier(['leftShift'])
        
        # make the key's case match for map search
        key_char = key.upper() if self._keycode_caps else key.lower()

        if key_char == ' ':
            key_char = 'SPACE'

        # find this key in the map
        scan_code = self.get_usb_scan_code(key_char)
        
        # wrapper function that converts/shifts the keycode the way ESXi expects it and then
        # returns an API object representing the key
        return USBHandler._convert_usb_code_to_esxi_obj(scan_code, modifiers=modifiers)

    def press_key(self, key: str):
        """
        Uses the ESXi API to simulate a key press on the remote VM.
        For non-alphanumeric keys, use 'press_usb_code' instead.

        The key is sent as if a user was writing over a UI. It is up to the user to ensure that the VM
        is in a state to properly receive the key press (i.e. the console is open if trying to write to
        a console).

        :param key:
            The key (as a string) to send through the ESXi API (e.g. 'a').
        """
        # Do the prep work to convert this string into a key object
        key_obj = self._prep_key(key)
        log.debug(f"{str(self)} Simulating key press: {key}")
        # create the UsbScanCode API object and inform this VM to send the provided code
        self._send_keys_to_esxi([key_obj])

    def send_usb_code(self, keycode: str, modifier_names=[]):
        """
        Uses the ESXi API to simulate a key press on the remote VM.
        This function expects a HEX value (e.g. '0x04' for 'a').
        Use 'press_key' if you would like the HEX values converted for you.

        The key is sent as if a user was writing over a UI. It is up to the user to ensure that the VM
        is in a state to properly receive the key press (i.e. the console is open if trying to write to
        a console).

        :param keycode:
            The key to send through the ESXi API.
        :param modifier_names: 
            A list of strings containing the names of the keys you wish to apply to another keypress.
            If an invalid option is provided: will throw an 'UsbScanCodeModifierError' Exception
            Valid options are: 

                - leftAlt
                - leftControl
                - leftGui
                - leftShift
                - rightAlt
                - rightControl
                - rightGui
                - rightShift
        """
        # apply modifiers (such as leftShift)
        modifiers = USBHandler._create_key_modifier(modifier_names)

        # wrapper function that converts/shifts the keycode the way ESXi expects it and then
        # returns an API object representing the key
        key_obj = USBHandler._convert_usb_code_to_esxi_obj(keycode, modifiers=modifiers)

        # create the UsbScanCode API object and inform this VM to send the provided code
        log.debug(f"{str(self)} Sending key code: '{keycode}' with modifier names: {modifier_names}")
        self._send_keys_to_esxi([key_obj])

    def write(self, text: str, enter: bool = False):
        """
        Uses the ESXi API to simulate writing text on the remote VM.

        The keys are sent as if a user was writing over a UI. It is up to the user to ensure that the VM
        is in a state to properly receive the key presses (i.e. the console is open if trying to write to
        a console). 

        :param text:
            The text to write through USB scan codes.
        :param enter:
            Boolean value whether to send the `ENTER` key after writing the text.
        """
        keys_to_press = []
        for key in text:
            key_obj = self._prep_key(key)
            keys_to_press.append(key_obj)
        
        if enter:
            enter_key_obj = self._prep_key('ENTER')
            keys_to_press.append(enter_key_obj)

        # create the UsbScanCode API object and inform this VM to send the provided codes
        log.debug(f"{str(self)} Simulating write: {text}")
        self._send_keys_to_esxi(keys_to_press)
    
    def get_usb_scan_code(self, key_name: str) -> str:
        """
        Finds the scan code for the provided key_name (if one is known).
        Throws a UsbScanCodeError exception if no key is found with that name.

        :param key_name:
            the name of the key to search for
        :return:
            the USB Scan code as a HEX string
        """
        try:
            return self._keycode_map[key_name]
        except KeyError:
            raise exceptions.UsbScanCodeError(self._vm, f'Provided key name: "{key_name}" does not have a USB scan code mapping.')

    def get_key_name_by_scan_code(self, hex_scan_code: str) -> str:
        """
        Finds the name for the provided scan code (if one is known).
        Throws a UsbScanCodeError exception if no name is found with that code.

        :param hex_scan_code:
            the name of the USB scan code to search for (as HEX)
        :return:
            the name of the key with that scan code
        """
        try:
            return usbkeycodes.USB_CODE_TO_KEY_NAME[hex_scan_code].replace(self._keycode_name_prefix, '')
        except KeyError:
            raise exceptions.UsbScanCodeError(self._vm, f'Provided USB HEX scan code: "{hex_scan_code}" either does not exist or does not have a name.')

    def _send_keys_to_esxi(self, key_objects: typing.List) -> int:
        """
        Aggregates a list of KeyEvent objects into a UsbScanCode object.
        Sends the object to esxi to press the requested keys.

        :param key_objects:
            a list of key objects representing keys to be pressed on the VM
        :return:
            the number of keys injected
        """
        usbsc = pyVmomi.vim.vm.UsbScanCodeSpec()
        usbsc.keyEvents = key_objects
        keys_sent = self._vm._vim_vm.PutUsbScanCodes(usbsc)
        log.debug(f'Sent: "{keys_sent}" keys to the VM.')

    def __str__(self):
        return f"<{type(self).__name__} for {self._vm.name}>"
    
    def __repr__(self):
        return str(self)

    @staticmethod
    def _convert_usb_code_to_esxi_key_code(usb_hex_code: str):
        """
        Takes a USB scan code (represented in hex) and converts it to the cooresponding number in ESXi.
        Sets all lower bits to '1'.

        :param usb_hex_code:
            the usb scancode to convert (e.g. '0x04' for 'a')
        :return:
            the keycode as understood by the ESXi API
        """
        return (int(usb_hex_code, 16) << 16) | 7

    @staticmethod
    def _create_keycode_maps(keycode_name_prefix: str = 'KEY_') -> typing.Tuple[typing.Dict]:
        """
        Expects a JSON file containing a mapping of usb scan codes and their string values.
        Outputs two Python maps for use.

        :param keycode_prefix:
            any prefix to remove from the front of each key name in the dict
        :return:
            Tuple containing hex_to_str and str_to_hex dictionaries for keycodes from the provided filepath
        """
        str_to_hex = {str(v).replace(keycode_name_prefix, ''): k for k, v in usbkeycodes.USB_CODE_TO_KEY_NAME.items()}
        return str_to_hex
    
    @staticmethod
    def _get_key_event_obj(esxi_code: int, modifiers=None):
        """
        Converts an ESXi code value into the API object that represents a key.

        :param esxi_code:
            the esxi code integer to convert to an object
        :param modifiers:
            A UsbScanCodeSpecModifierType to attach to the key object (see _create_key_modifier)
        :return:
            the KeyEvent object used by the UsbScanCodeSpec object
        """
        ke = pyVmomi.vim.vm.UsbScanCodeSpec.KeyEvent()
        ke.usbHidCode = esxi_code
        if modifiers:
            ke.modifiers = modifiers
        return ke
    
    @staticmethod
    def _create_key_modifier(modifier_names: typing.List[str]):
        """
        Inputs a list of key names that you wish to apply as modifiers to a key and outputs an API object representing the modifiers.
        :param modifier_names: 
            A list of strings containing the names of the keys you wish to apply to another keypress.
            If an invalid option is provided: will throw an 'UsbScanCodeModifierError' Exception
            Valid options are: 

                - leftAlt
                - leftControl
                - leftGui
                - leftShift
                - rightAlt
                - rightControl
                - rightGui
                - rightShift
            
        :return:
            An API object representing all the modifiers applied
        """
        km = pyVmomi.vim.UsbScanCodeSpecModifierType()
        for m in modifier_names:
            m = m.strip().lower().replace(' ', '')
            if m == 'leftshift':
                km.leftShift = True
            elif m == 'rightshift':
                km.rightShift = True
            elif m == 'leftalt':
                km.leftAlt = True
            elif m == 'rightalt':
                km.rightAlt = True
            elif m == 'leftcontrol':
                km.leftControl = True
            elif m == 'rightcontrol':
                km.rightControl = True
            elif m == 'leftgui':
                km.leftGui = True
            elif m == 'rightgui':
                km.rightGui = True
            else:
                raise exceptions.UsbScanCodeModifierError(f'{m} is not a valid modifier type!')
        return km
    
    @staticmethod
    def _convert_usb_code_to_esxi_obj(usb_hex_code: str, modifiers=None):
        """
        Takes a USB scan code (represented in hex) and converts it into the API object that represents a key.

        :param usb_hex_code:
            the usb scancode to convert (e.g. '0x04' for 'a')
        :param modifiers:
            A UsbScanCodeSpecModifierType to attach to the key object (see _create_key_modifier)
        :return:
            the KeyEvent object used by the UsbScanCodeSpec object
        """
        return USBHandler._get_key_event_obj(USBHandler._convert_usb_code_to_esxi_key_code(usb_hex_code), modifiers=modifiers)
    
    @staticmethod
    def _get_base_key(key: str):
        """
        Gets the 'non-shift' character associated with a shifted character.

        :param key:
            the desired character
        :return:
            the base key/character on the keyboard
        """
        if key == '~':
            key = '`'
        elif key == '!':
            key = '1'
        elif key == '@':
            key = '2'
        elif key == '#':
            key = '3'
        elif key == '$':
            key = '4'
        elif key == '%':
            key = '5'
        elif key == '^':
            key = '6'
        elif key == '&':
            key = '7'
        elif key == '*':
            key = '8'
        elif key == '(':
            key = '9'
        elif key == ')':
            key = '0'
        elif key == '_':
            key = '-'
        elif key == '+':
            key = '='
        elif key == '{':
            key = '['
        elif key == '}':
            key = ']'
        elif key == '|':
            key = '\\'
        elif key == ':':
            key = ';'
        elif key == '"':
            key = '\''
        elif key == '<':
            key = ','
        elif key == '>':
            key = '.'
        elif key == '?':
            key = '/'
        return key
