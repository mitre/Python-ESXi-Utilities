# Changelog

This page was created to track changes to versions of Python-ESXi-Utilities (esxi_utils). The changelog was created in v3.22.1 and only changes starting from that version are tracked here.

## 4.0.0

- Changes the default method of retrieving VirtualMachine objects from their list
    - From: Being scoped just to the 'child' server in a vCenter
    - To: All available virtual machines as visible via the vCenter inventory
    - The old method of getting a list of virtual machines is available by specifying legacy_list=True to the ESXiClient object when creating it
- Adds support for Virtual Machine 'Templates' in vCenter arrangements
    - vm.is_template() for determining if a VM has been converted to a template
    - vm.to_template() to convert a VM to a clonable template (THIS CANNOT BE UNDONE)
    - vm.deploy_from_template(...) to create a new VM from a VM template
- Adds a new client.is_vcenter() method to the ESXi client object

## 3.22.1

- Adds metadata to pip package for PyPI
- Pins setuptools version and updates requests pinned version
