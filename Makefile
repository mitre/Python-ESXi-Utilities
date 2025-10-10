help:
	@echo "Usage: make <command>"
	@echo "Commands:"
	@echo "\tbuild: Build the package for distribution or installation."
	@echo "\tinstall: Install the built package locally."
	@echo "\tremove: Remove the local installed package."
	@echo "\tall: Remove locally installed package, then build and re-install it."

build:
	python3 -m build

install:
	pip install dist/*.whl

remove:
	rm -rf dist
	pip uninstall -y esxi_utils

all: remove build install
	
.PHONY: build install remove all