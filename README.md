©2025 The MITRE Corporation. ALL RIGHTS RESERVED.
 
The author's affiliation with The MITRE Corporation is provided for identification purposes only, and is not intended to convey or imply MITRE's concurrence with, or support for, the positions, opinions, or viewpoints expressed by the author.'©2025 The MITRE Corporation. ALL RIGHTS RESERVED.
NOTICE
 
This software was produced for the U. S. Government under Basic Contract No. W56KGU-18-D-0004, and is subject to the Rights in Noncommercial Computer Software and Noncommercial Computer Software Documentation Clause 252.227-7014 (FEB 2014)

# Documentation

Ensure Sphinx is installed with `pip install sphinx` and then run `make` in the `docs/` directory.


# Examples

Some basic examples are included here for common functionality. For more detailed information, see the generated documentation.

## Initialize a client
```python
import esxi_utils
client = esxi_utils.ESXiClient("<ip>", "<username>", "<password>")
```

Note: The remaining examples will assume an already-initialized client.


## Get Virtual Machine Information
```python
# Print all VM names
print("All VMs: " + str(client.vms.names))

# Check if a VM exists
if "MyVirtualMachine" not in client.vms:  # Or more explicitly: if not client.vms.exists("MyVirtualMachine"):
   raise Exception("VM does not exist")

# Get a VM object
vm = client.vms["MyVirtualMachine"]       # Or more explicitly: vm = client.vms.get("MyVirtualMachine")

# Print this VMs information
print("Name: " + vm.name)
print("ID: " + str(vm.id))
print("UUID: " + vm.uuid)
print("Name of datastore containing this VM: " + vm.datastore.name)
print("Is powered on: " + str(vm.powered_on))
print("Number of VCPUs: " + str(vm.vcpus))
print("MB of memory: " + str(vm.memory))
print("VM OS Type: " + vm.guestid)

for disk in vm.disks:
   print("Disk size (KB): " + str(disk.size))

for nic in vm.nics:
   print("Network: " + nic.network + " (IP: " + nic.ip + ")")

for cdrom in vm.cdroms:
   print("CD-ROM: " + str(cdrom.file))

for snapshot in vm.snapshots:
   print("Snapshot: name=" + snapshot.name + ", description=" + snapshot.description + ", created=" + str(snapshot.createtime))
```


## Create a new Virtual Machine and Add Hardware
```python
vm = client.vms.create(
   name="MyNewVirtualMachine",
   datastore="MyDatastore",
   vcpus=1,
   memory="2GB",
   guestid="rhel7_64Guest"
)

# Add a disk
vm.disks.add("10GB")

# Add a NIC
vm.nics.add("Test-Network")

# Add a CD
cdrom_file = client.datastores["MyDatastore"].filepath("my-file.iso")	# Or: client.datastores["MyDatastore"].root / "my-file.iso"
cdrom = vm.cdroms.add(cdrom_file)
cdrom.start_connected = True

# Add a Floppy
floppy_file = client.datastores["MyDatastore"].filepath("my-floppy.img")
floppy = vm.floppies.add(floppy_file)
floppy.start_connected = True
```


## Modify an existing Virtual Machine
```python
vm = client.vms["MyVirtualMachine"]

vm.power_off()                  # Power off the virtual machine
vm.memory = "8GB"               # Set memory to 8GB
vm.vcpus = 4                    # Set number of VCPUs to 4
vm.guestid = "rhel7_64Guest"    # Set ESXi OS Type

# Modify a NIC
nic = vm.nics["External"]               # Get the NIC for network "External"; Or more explicitly: nic = vm.nics.get("External")
nic.network = "Management-Network"      # Change the NIC's network to "Management-Network"
nic.connected = True                    # Connect the NIC

# Remove a NIC
vm.nics["Other-Network"].remove()

# Resize the first disk
vm.disks[0].size = "32GB"

# Remove the second disk
vm.disks[1].remove()

# Change the CD-ROM file
vm.cdroms[0].file = client.datastores["MyDatastore"].filepath("installer.iso")

# Change the floppy file
vm.floppies[0].file = client.datastores["MyDatastore"].filepath("kickstart.img")
```


## Work with Virtual Machine Snapshots
```python
vm = client.vms["MyVirtualMachine"]

# Create a new snapshot
vm.snapshots.create("MyNewSnapshot", description="This is a new snapshot")

# Remove the current snapshot
vm.snapshots.current.remove(remove_children=True)

# Revert to an old snapshot
vm.snapshots["MyOldSnapshot"].revert()
```


## Upload a Virtual Machine from OVF or OVA
```python
vm = client.vms.upload(
   file="./path/to/file.ovf",
   datastore="MyDatastore",
   name="MyNewVirtualMachine",
   network_mappings={ "Original-Network": "New-Network" }
)

vm.power_on()
```


## Export a Virtual Machine to OVF or OVA
```python
client.vms["MyVirtualMachine"].export(
   path="./path/to/export/folder",
   format="ova",
   hash_type="sha256",
   include_image_files=False,
   include_nvram=True
)
```


## Clone a Virtual Machine
```python
vm = client.vms["MyVirtualMachine"].clone("MyNewVirtualMachine")
vm.power_on()
```


## Print Networking Information
```python
print("Host VSwitches:")
for vswitch in client.vswitches:
	print("\tName:" + vswitch.name)
	print("\t\tMTU: " + str(vswitch.mtu))
	print("\t\tPorts Available: " + str(vswitch.numports_available) + " / " + str(vswitch.numports))
	print("\t\tPort groups:")
	for portgroup in vswitch.portgroups:
		print("\t\t\t- " + portgroup.name)
print()

print("Host Port Groups:")
for portgroup in client.portgroups:
	print("\tName: " + portgroup.name)
	print("\t\tVLAN: " + str(portgroup.vlan))
	print("\t\tActive Clients: " + str(portgroup.active_clients))
	print("\t\tVSwitch: " + portgroup.vswitch.name)
	print("\t\tConnected VMs:")
	for vm in portgroup.vms:
		print("\t\t\t- " + vm.name)
print()

print("Host Physical NICs:")
for pnic in client.physicalnics:
	print("\tName: " + pnic.name)
	print("\t\tUp: " + str(pnic.up))
	print("\t\tLink Speed (MB): " + str(pnic.linkspeed))
	print("\t\tFull Duplex: " + str(pnic.fullduplex))
print()

print("Host VMKernel NICs:")
for vnic in client.vmkernelnics:
	print("\tName: " + vnic.name)
	print("\t\tPort Group: " + str(vnic.portgroup))
	print("\t\tIP: " + vnic.ip)
	print("\t\tSubnet: " + vnic.subnetmask)
	print("\t\tMTU: " + str(vnic.mtu))
```

## Modify Networking
```python
# Check if a virtual switch exists
exists = "MyVirtualSwitch" in client.vswitches
print("VSwitch exists: " + str(exists))

# Check if a port groups exists
exists = "MyPortGroup" in client.portgroups
print("PortGroup exists: " + str(exists))

# Add new virtual switch and port groups
vswitch = client.vswitches.add("TestVSwitch")
vswitch.add("TestPortGroup", vlan=70)
vswitch.add("TestPortGroup2", vlan=80)

# Remove a port group from a virtual switch
client.vswitches["TestVSwitch"].portgroups[0].remove()

# Remove a virtual switch
client.vswitches["TestVSwitch"].remove()

# Add a port group to an existing virtual switch
client.vswitches["AVirtualSwitch"].add("APortGroup", vlan=0)
client.vswitches["AVirtualSwitch"].add("APortGroup2", vlan=4095)
```

# Development

## References

Please refer to Broadcom's website for the latest documentation.

(This documentation no longer exists):
[Vsphere documentation](https://developer.vmware.com/apis/358/vsphere)
