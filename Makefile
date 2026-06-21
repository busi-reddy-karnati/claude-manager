# claude-manager — build & install the single-file CLI.
#
#   make build      build dist/claude-manager (a self-contained zipapp)
#   make install    install it to $(BIN_DIR)
#   make uninstall  remove it
#   make test       run the test suite
#   make clean      remove build artifacts

PYTHON ?= python3
PREFIX ?= $(HOME)/.local
BIN_DIR ?= $(PREFIX)/bin
APP := claude-manager
DIST := dist/$(APP)

.PHONY: build install uninstall test clean

build: $(DIST)

$(DIST): $(wildcard claude_manager/*.py)
	@mkdir -p dist build
	@rm -rf build/stage && mkdir -p build/stage
	@cp -R claude_manager build/stage/
	$(PYTHON) -m zipapp build/stage \
		-m "claude_manager.cli:main" \
		-p "/usr/bin/env python3" \
		-o $(DIST)
	@chmod 0755 $(DIST)
	@$(DIST) --version >/dev/null && echo "built $(DIST)"

install: build
	@mkdir -p $(BIN_DIR)
	@cp $(DIST) $(BIN_DIR)/$(APP)
	@chmod 0755 $(BIN_DIR)/$(APP)
	@echo "installed $(APP) -> $(BIN_DIR)/$(APP)"
	@case ":$$PATH:" in *":$(BIN_DIR):"*) ;; \
		*) echo "note: $(BIN_DIR) is not on your PATH; add: export PATH=\"$(BIN_DIR):\$$PATH\"" ;; \
	esac

uninstall:
	@rm -f $(BIN_DIR)/$(APP)
	@echo "removed $(BIN_DIR)/$(APP)"

test:
	$(PYTHON) -m pytest tests/ -q

clean:
	@rm -rf build dist
	@echo "cleaned build artifacts"
