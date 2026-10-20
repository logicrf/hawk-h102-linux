ifneq ($(KERNELRELEASE),)
obj-m += h102_axi_reg.o
obj-m += h102_axi_trig.o
else
KERNEL_PATH ?= $(KERNEL_SRC)
KERNEL_PATH ?= /lib/modules/$(shell uname -r)/build

.PHONY: all modules modules_install clean

all: modules

modules:
	$(MAKE) -C $(KERNEL_PATH) M=$(CURDIR) O=$(O) modules

modules_install:
	$(MAKE) -C $(KERNEL_PATH) M=$(CURDIR) O=$(O) modules_install

clean:
	$(MAKE) -C $(KERNEL_PATH) M=$(CURDIR) O=$(O) clean
endif
